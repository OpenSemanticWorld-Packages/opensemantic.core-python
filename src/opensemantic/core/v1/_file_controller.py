"""v1 file controller classes for opensemantic.core.

Composes the controller mixins with the v1 file models. Importing this module
registers the controllers, which is what makes them findable through
:func:`get_file_controller`.
"""

from io import BytesIO
from typing import Any, List, Optional

from pydantic import ConfigDict
from pydantic.v1 import Field

from opensemantic.core._file_controller_mixin import (  # noqa: F401 (re-export)
    FileControllerMixin,
    InMemoryControllerMixin,
    LocalFileControllerMixin,
    RemoteFileControllerMixin,
    get_file_controller,
)
from opensemantic.core.v1._model import Label as _Label
from opensemantic.core.v1._model import LocalFile as _LocalFile
from opensemantic.core.v1._model import RemoteFile as _RemoteFile

FileController = FileControllerMixin
"""The interface of the file controllers.

Not bound to ``File``: a file entity that is neither local nor remote carries
no way to reach its content, so it has no handler in the registry.
"""


class LocalFileController(LocalFileControllerMixin, _LocalFile):
    """Reads and writes the file at ``local_path`` (v1)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    label: Optional[List[_Label]] = [_Label(text="Unnamed file")]


class InMemoryController(InMemoryControllerMixin, _LocalFile):
    """Holds the content in memory (v1)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    label: Optional[List[_Label]] = [_Label(text="Unnamed stream")]

    stream: Any = Field(default_factory=BytesIO)
    """The buffer holding the content, byte oriented to match get/put."""


class RemoteFileController(RemoteFileControllerMixin, _RemoteFile):
    """Downloads the file behind ``download_url`` / ``access_url`` (v1)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    label: Optional[List[_Label]] = [_Label(text="Unnamed file")]
