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

import shutil
from abc import abstractmethod
from io import BytesIO, TextIOBase
from pathlib import Path
from typing import IO, Any, Dict, Optional
from urllib.parse import urlsplit

from oold.model import BaseController
from oold.model import find_controller_type as _v2_find_controller
from oold.model.v1 import find_controller_type as _v1_find_controller


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

    @property
    def path(self) -> Path:
        if not self.local_path:
            raise ValueError(f"{type(self).__name__} has no local_path set")
        return Path(self.local_path)

    def get(self) -> IO:
        return open(self.path, "rb")

    def put(self, file: IO, **kwargs: Dict[str, Any]) -> None:
        mode = "w" if isinstance(file, TextIOBase) else "wb"
        with open(self.path, mode) as f:
            shutil.copyfileobj(file, f)

    def delete(self) -> None:
        path = self.path
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
        """
        return BytesIO(self.stream.getvalue())

    def put(self, file: IO, **kwargs: Dict[str, Any]) -> None:
        """Replace the content, as writing to a file would."""
        data = file.read()
        if isinstance(data, str):
            data = data.encode()
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
    from pydantic.v1 import BaseModel as BaseModelV1

    return isinstance(obj, BaseModelV1)


def _apply(controller, kwargs: Dict[str, Any]):
    """Set the requested attributes on an already-built controller.

    The caller passes what the controller needs to work - a session, a set of
    credentials. Rebuilding it instead would drop whatever runtime state it
    already carries, so the attributes go onto the instance it handed in.
    """
    for name, value in kwargs.items():
        setattr(controller, name, value)
    return controller


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
    return file.cast(cls, **kwargs)
