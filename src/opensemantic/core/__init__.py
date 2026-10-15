from importlib.metadata import PackageNotFoundError, version  # pragma: no cover

try:
    # Change here if project is renamed and does not equal the package name
    dist_name = "opensemantic.core"
    __version__ = version(dist_name)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"
finally:
    del version, PackageNotFoundError

# Imported for the side effect of registering the controllers, so a caller that
# only holds a file entity can find them through get_file_controller.
from opensemantic.core._file_controller import (  # noqa: E402,F401
    FileController,
    FileControllerMixin,
    InMemoryController,
    LocalFileController,
    RemoteFileController,
    get_file_controller,
)
from opensemantic.core._model import *  # noqa

# Assignments, not imports: isort sorts an import above the star import, which
# would put the pure models back. These names resolve to the controllers that
# implement them, so a file entity a caller builds can read and write itself.
LocalFile = LocalFileController
RemoteFile = RemoteFileController
