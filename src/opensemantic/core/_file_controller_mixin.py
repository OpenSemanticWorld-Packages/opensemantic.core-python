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
from io import TextIOBase
from pathlib import Path
from typing import IO, Any, ClassVar, Dict, Optional

from oold.model import BaseController

try:
    from oold.model import get_registered_controller_types as _v2_controllers
except ImportError:  # oold without the public lookup
    from oold.model import _controller_types as _v2_registry

    def _v2_controllers(iri):
        return list(_v2_registry.get(iri, []))


try:
    from oold.model.v1 import get_registered_controller_types as _v1_controllers
except ImportError:  # oold without the public lookup
    from oold.model.v1 import _controller_types as _v1_registry

    def _v1_controllers(iri):
        return list(_v1_registry.get(iri, []))


class FileControllerMixin(BaseController):
    """Byte-level access to a file entity.

    Implementations provide ``get`` and ``put``; the transfer helpers are
    defined in terms of those, so any two implementations can exchange content.
    """

    handles_entity_type: ClassVar[bool] = True
    """Whether :func:`get_file_controller` may pick this controller for an
    entity of its type. Utility controllers that reuse a model without being
    its natural handler set this to False."""

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

    Reuses the local file model without being the handler for it, so the
    registry lookup keeps returning the controller that reads ``local_path``.
    """

    handles_entity_type: ClassVar[bool] = False

    def get(self) -> IO:
        self.stream.seek(0)
        return self.stream

    def put(self, file: IO, **kwargs: Dict[str, Any]) -> None:
        shutil.copyfileobj(file, self.stream)
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
        if not url.startswith(("http:", "https:")):
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
        return file
    type_iris = getattr(file, "type", None) or []
    if isinstance(type_iris, str):
        type_iris = [type_iris]

    fallback = None
    for iri in type_iris:
        # The pydantic v1 and v2 models keep separate registries, so both are
        # consulted. Later registrations win, so a downstream package overrides
        # an implementation by importing its own controller for the same type.
        candidates = _v2_controllers(iri) + _v1_controllers(iri)
        for cls in reversed(candidates):
            if not (issubclass(cls, FileControllerMixin) and cls.handles_entity_type):
                continue
            # The v1 and v2 models share their type IRIs, so prefer the
            # controller built on the entity's own model.
            if issubclass(cls, type(file)):
                return file.cast(cls, **kwargs)
            if fallback is None:
                fallback = cls
    if fallback is None:
        return None
    return file.cast(fallback, **kwargs)
