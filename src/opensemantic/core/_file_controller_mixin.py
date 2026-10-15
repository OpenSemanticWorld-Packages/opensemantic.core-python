"""Controller mixins for reading and writing the content of file entities.

The models describe a file (``File``, ``LocalFile``, ``RemoteFile``); these
mixins add the byte-level access, following the controller idiom of the other
packages: a version-agnostic mixin on ``BaseController`` plus a per-version
class that binds it to the matching model.

A caller that holds a file entity does not need to know which implementation
applies: :func:`get_file_controller` maps the entity's type IRI to a registered
controller, so a package that only depends on ``opensemantic.core`` can still
materialize a file whose controller lives elsewhere.
"""

import logging
import shutil
from abc import abstractmethod
from io import BytesIO, TextIOBase
from pathlib import Path
from typing import IO, Any, Dict, Optional
from urllib.parse import urlsplit

from oold.model import BaseController
from oold.model import find_controller_type as _v2_find_controller
from oold.model.v1 import find_controller_type as _v1_find_controller
from pydantic.v1 import BaseModel as _BaseModelV1

_logger = logging.getLogger(__name__)

TEXT_ENCODING = "utf-8"
"""How a text stream is turned into the bytes a file holds.

Fixed rather than taken from the locale, so the same text written through any
of these controllers, on any machine, is the same file.
"""


class FileControllerMixin(BaseController):
    """Byte-level access to a file entity.

    Implementations provide ``get`` and ``put``; the transfer helpers are
    defined in terms of those, so any two implementations can exchange content.
    """

    @abstractmethod
    def get(self) -> IO:
        """Read or download the file.

        The caller closes the returned object.

        Returns
        -------
            the IO object of the opened file
        """
        raise NotImplementedError

    @abstractmethod
    def put(self, file: IO, **kwargs: Dict[str, Any]) -> None:
        """Write or upload the content of an IO object.

        Parameters
        ----------
        file
            the IO object to read from
        """
        raise NotImplementedError

    def put_from(self, other: "FileControllerMixin", **kwargs: Dict[str, Any]) -> None:
        """Write the content of another file controller into this one.

        Closes the other controller's IO object after reading.
        """
        with other.get() as f:
            self.put(f, **kwargs)

    def get_to(self, other: "FileControllerMixin") -> None:
        """Write this file's content into another file controller.

        Closes this controller's IO object after reading.
        """
        with self.get() as f:
            other.put(f)

    @classmethod
    def from_other(cls, other: "FileControllerMixin", **kwargs: Any):
        """Create an instance from another file controller, copying common fields.

        Parameters
        ----------
        other
            the file controller to copy from
        kwargs
            additional attributes to set on the new instance
        """
        return other.cast(cls, **kwargs)


class LocalFileControllerMixin(FileControllerMixin):
    """File content stored at ``local_path``."""

    def resolve_path(self) -> Path:
        """``local_path`` as a ``Path``, or a readable error if it is unset.

        A method, not a ``path`` property: the controller extends a model whose
        field names come from a schema, and a property named like a field wins
        over that field in attribute lookup, so the field's value becomes
        unreadable. A verb cannot be mistaken for data.
        """
        if not self.local_path:
            raise ValueError(f"{type(self).__name__} has no local_path set")
        return Path(self.local_path)

    def get(self) -> IO:
        return open(self.resolve_path(), "rb")

    def put(self, file: IO, **kwargs: Dict[str, Any]) -> None:
        target = self.resolve_path()
        if isinstance(file, TextIOBase):
            # explicit utf-8, not the locale encoding: the same text put into
            # the in-memory controller has to come out as the same bytes, or a
            # transfer between the two mangles anything outside ASCII
            with open(target, "w", encoding=TEXT_ENCODING) as f:
                shutil.copyfileobj(file, f)
            return
        with open(target, "wb") as f:
            shutil.copyfileobj(file, f)

    def delete(self) -> None:
        path = self.resolve_path()
        if path.exists():
            path.unlink()


class InMemoryControllerMixin(FileControllerMixin):
    """File content held in memory, for tests and intermediate transfers.

    Reuses the local file model without being the handler for it: it is
    requested explicitly, ``InMemoryController(local_file)``, and stays out of
    the registry so the lookup keeps returning the controller that reads
    ``local_path``.
    """

    __oold_register__ = False

    def get(self) -> IO:
        """A reader over the content, independent of the buffer.

        The caller closes what ``get`` returns - the mixin's own ``put_from``
        and ``get_to`` do, and so does base's ``materialize_data``. Handing out
        the live buffer would make the first read the last one.

        Bytes, whatever the buffer holds: a transfer target writes binary, and
        a controller that answered sometimes with text and sometimes with bytes
        would make every caller test for it.
        """
        data = self.stream.getvalue()
        return BytesIO(data.encode(TEXT_ENCODING) if isinstance(data, str) else data)

    def put(self, file: IO, **kwargs: Dict[str, Any]) -> None:
        """Replace the content, as writing to a file would."""
        data = file.read()
        text_buffer = isinstance(self.stream, TextIOBase)
        if isinstance(data, str) and not text_buffer:
            data = data.encode(TEXT_ENCODING)
        elif isinstance(data, bytes) and text_buffer:
            data = data.decode(TEXT_ENCODING)
        self.stream.seek(0)
        self.stream.truncate(0)
        self.stream.write(data)
        self.stream.seek(0)


class RemoteFileControllerMixin(FileControllerMixin):
    """File content behind a URL.

    ``get`` follows ``download_url`` (falling back to ``access_url``) with the
    standard library, so a plain HTTP distribution needs no extra dependency.
    ``put`` has no generic counterpart and is left to the implementations.
    """

    def _url(self) -> str:
        url = self.download_url or self.access_url
        if not url:
            raise ValueError(
                f"{type(self).__name__} has neither download_url nor access_url set"
            )
        return url

    def get(self) -> IO:
        from urllib.request import urlopen

        url = self._url()
        # RFC 3986 says the scheme is case-insensitive; urlsplit normalizes it
        if urlsplit(url).scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme: {url}")
        return urlopen(url)  # noqa: S310 - scheme checked above

    def put(self, file: IO, **kwargs: Dict[str, Any]) -> None:
        """Not available generically: uploading is protocol specific.

        Kept concrete so a remote file stays readable without a
        protocol-specific controller.
        """
        raise NotImplementedError(
            f"{type(self).__name__} cannot upload; use a controller for the "
            "protocol of this file"
        )


def _is_v1(obj) -> bool:
    """Whether the entity is a pydantic v1 model."""
    return isinstance(obj, _BaseModelV1)


def _declared_fields(cls) -> Optional[Dict[str, Any]]:
    """The field map of a model class, or ``None`` if it is not one."""
    for attribute in ("model_fields", "__fields__"):
        fields = getattr(cls, attribute, None)
        if isinstance(fields, dict):
            return fields
    return None


def _accepted(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """The kwargs ``cls`` can take.

    A caller hands over what it has - a session, a set of credentials - without
    knowing which controller will answer, so what a model does not declare is
    not for it; passing it on would fail construction. A controller that is not
    a model declares nothing, so it is given everything and decides for itself.
    """
    fields = _declared_fields(cls)
    if fields is None:
        return dict(kwargs)
    unknown = [name for name in kwargs if name not in fields]
    if unknown:
        _logger.debug("%s ignores %s", cls.__name__, ", ".join(sorted(unknown)))
    return {name: value for name, value in kwargs.items() if name in fields}


def _apply(controller, kwargs: Dict[str, Any]):
    """The controller with the requested attributes set.

    A model is copied rather than written to: the caller handed in a controller
    it goes on using, and re-pointing that one at another file - or another
    session - behind its back is not what asking for a controller means. An
    object that is not a model cannot be copied field-wise, so it is updated in
    place.
    """
    accepted = _accepted(type(controller), kwargs)
    if not accepted:
        return controller
    if _declared_fields(type(controller)) is None:
        for name, value in accepted.items():
            setattr(controller, name, value)
        return controller
    copy = getattr(controller, "model_copy", None) or controller.copy
    return copy(update=accepted)


def get_file_controller(file, **kwargs) -> Optional[FileControllerMixin]:
    """The file controller for a file entity, or ``None`` if none is registered.

    Resolves the entity's type IRI against the controller registry, so the
    caller neither imports nor knows the concrete implementation. A controller
    only appears here once its defining module has been imported.

    Parameters
    ----------
    file
        the file entity to wrap
    kwargs
        additional attributes to set on the controller

    Returns
    -------
        the controller instance, or ``None`` when the entity's type has no
        registered file controller
    """
    if isinstance(file, FileControllerMixin):
        return _apply(file, kwargs)
    # A controller from elsewhere answers to get/put without sharing the mixin.
    if callable(getattr(file, "get", None)) and callable(getattr(file, "put", None)):
        return _apply(file, kwargs)
    type_iris = getattr(file, "type", None) or []
    if isinstance(type_iris, str):
        type_iris = [type_iris]

    # The v1 and v2 models share their type IRIs but keep separate registries,
    # so the entity's own layer decides which one answers. A class of the other
    # flavour would not validate the entity's data.
    find = _v1_find_controller if _is_v1(file) else _v2_find_controller
    cls = find(type_iris, base=FileControllerMixin)
    if cls is None:
        return None
    return file.cast(cls, **_accepted(cls, kwargs))
