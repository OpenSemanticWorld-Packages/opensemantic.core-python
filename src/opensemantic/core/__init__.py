from importlib.metadata import PackageNotFoundError, version  # pragma: no cover

try:
    # Change here if project is renamed and does not equal the package name
    dist_name = "opensemantic.core"
    __version__ = version(dist_name)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"
finally:
    del version, PackageNotFoundError

# After the star import above, which would otherwise put the pure models back:
# these names resolve to the controllers that implement them.
# Imported for the side effect of registering the controllers, so a caller that
# only holds a file entity can find them through get_file_controller.
from opensemantic.core._file_controller import (  # noqa: E402,F401
    FileController,
    FileControllerMixin,
    InMemoryController,
    LocalFile,
    LocalFileController,
    RemoteFile,
    RemoteFileController,
    get_file_controller,
)
from opensemantic.core._model import *  # noqa
