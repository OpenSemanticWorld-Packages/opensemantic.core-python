"""Tests for the file controllers.

Covers the local, in-memory and remote implementations, the transfer helpers
between them, and the registry lookup that lets a caller materialize a file
entity without knowing the concrete controller.
"""

import io
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

import opensemantic.core as v2
import opensemantic.core.v1 as v1
from opensemantic.core import get_file_controller

MODULES = [pytest.param(v2, id="v2"), pytest.param(v1, id="v1")]

CONTENT = b"the file content"


def _local(mod, path, text="Test File"):
    return mod.LocalFileController(label=[mod.Label(text=text)], local_path=str(path))


@pytest.mark.parametrize("mod", MODULES)
def test_local_put_and_get(mod, tmp_path):
    controller = _local(mod, tmp_path / "a.bin")
    controller.put(io.BytesIO(CONTENT))
    assert (tmp_path / "a.bin").read_bytes() == CONTENT
    with controller.get() as f:
        assert f.read() == CONTENT


@pytest.mark.parametrize("mod", MODULES)
def test_local_put_accepts_a_text_stream(mod, tmp_path):
    controller = _local(mod, tmp_path / "a.txt")
    controller.put(io.StringIO("text content"))
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "text content"


@pytest.mark.parametrize("mod", MODULES)
def test_local_delete(mod, tmp_path):
    path = tmp_path / "a.bin"
    controller = _local(mod, path)
    controller.put(io.BytesIO(CONTENT))
    assert path.exists()
    controller.delete()
    assert not path.exists()
    controller.delete()  # a missing file is not an error


@pytest.mark.parametrize("mod", MODULES)
def test_local_without_path_fails_clearly(mod):
    controller = mod.LocalFileController(label=[mod.Label(text="No path")])
    with pytest.raises(ValueError, match="local_path"):
        controller.get()


@pytest.mark.parametrize("mod", MODULES)
def test_put_from_copies_between_controllers(mod, tmp_path):
    source = _local(mod, tmp_path / "source.bin")
    source.put(io.BytesIO(CONTENT))

    memory = mod.InMemoryController(label=[mod.Label(text="Stream")])
    memory.put_from(source)
    assert memory.get().read() == CONTENT


@pytest.mark.parametrize("mod", MODULES)
def test_get_to_copies_between_controllers(mod, tmp_path):
    source = _local(mod, tmp_path / "source.bin")
    source.put(io.BytesIO(CONTENT))
    target = _local(mod, tmp_path / "target.bin")

    source.get_to(target)
    assert (tmp_path / "target.bin").read_bytes() == CONTENT


@pytest.mark.parametrize("mod", MODULES)
def test_in_memory_round_trip(mod):
    memory = mod.InMemoryController(label=[mod.Label(text="Stream")])
    memory.put(io.BytesIO(CONTENT))
    assert memory.get().read() == CONTENT
    assert memory.get().read() == CONTENT  # re-readable


@pytest.mark.parametrize("mod", MODULES)
def test_from_other_copies_common_fields(mod, tmp_path):
    entity = mod.LocalFile(
        label=[mod.Label(text="Named")], local_path=str(tmp_path / "a.bin")
    )
    controller = mod.LocalFileController.from_other(entity)
    assert isinstance(controller, mod.LocalFileController)
    assert controller.label[0].text == "Named"
    assert controller.local_path == str(tmp_path / "a.bin")


# -- registry lookup --


@pytest.mark.parametrize("mod", MODULES)
def test_lookup_returns_the_local_controller(mod, tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(CONTENT)
    entity = mod.LocalFile(label=[mod.Label(text="A")], local_path=str(path))

    controller = get_file_controller(entity)

    assert isinstance(controller, mod.LocalFileController)
    with controller.get() as f:
        assert f.read() == CONTENT


@pytest.mark.parametrize("mod", MODULES)
def test_lookup_returns_the_remote_controller(mod):
    entity = mod.RemoteFile(
        label=[mod.Label(text="R")], download_url="https://example.org/a.bin"
    )
    assert isinstance(get_file_controller(entity), mod.RemoteFileController)


@pytest.mark.parametrize("mod", MODULES)
def test_lookup_picks_the_controller_of_the_entity_version(mod):
    """v1 and v2 share type IRIs, so the entity's own model decides."""
    entity = mod.LocalFile(label=[mod.Label(text="A")], local_path="/tmp/a.bin")
    controller = get_file_controller(entity)
    assert type(controller).__module__ == mod.LocalFileController.__module__


@pytest.mark.parametrize("mod", MODULES)
def test_lookup_skips_the_in_memory_controller(mod):
    """It reuses the local file model without being its handler."""
    entity = mod.LocalFile(label=[mod.Label(text="A")], local_path="/tmp/a.bin")
    assert not isinstance(get_file_controller(entity), mod.InMemoryController)


@pytest.mark.parametrize("mod", MODULES)
def test_lookup_returns_none_for_a_file_without_content_access(mod):
    """A plain File is neither local nor remote, so nothing can read it."""
    assert get_file_controller(mod.File(label=[mod.Label(text="F")])) is None


@pytest.mark.parametrize("mod", MODULES)
def test_lookup_passes_through_a_controller(mod, tmp_path):
    controller = _local(mod, tmp_path / "a.bin")
    assert get_file_controller(controller) is controller


# -- remote --


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(CONTENT)))
        self.end_headers()
        self.wfile.write(CONTENT)

    def log_message(self, *args):
        pass


@pytest.fixture
def http_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/a.bin"
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("mod", MODULES)
def test_remote_get_downloads(mod, http_server):
    controller = mod.RemoteFileController(
        label=[mod.Label(text="R")], download_url=http_server
    )
    with controller.get() as f:
        assert f.read() == CONTENT


@pytest.mark.parametrize("mod", MODULES)
def test_remote_get_falls_back_to_access_url(mod, http_server):
    controller = mod.RemoteFileController(
        label=[mod.Label(text="R")], access_url=http_server
    )
    with controller.get() as f:
        assert f.read() == CONTENT


@pytest.mark.parametrize("mod", MODULES)
def test_remote_without_url_fails_clearly(mod):
    controller = mod.RemoteFileController(label=[mod.Label(text="R")])
    with pytest.raises(ValueError, match="download_url"):
        controller.get()


@pytest.mark.parametrize("mod", MODULES)
def test_remote_rejects_a_non_http_url(mod):
    controller = mod.RemoteFileController(
        label=[mod.Label(text="R")], download_url="file:///etc/passwd"
    )
    with pytest.raises(ValueError, match="scheme"):
        controller.get()


@pytest.mark.parametrize("mod", MODULES)
def test_remote_put_is_not_generic(mod):
    controller = mod.RemoteFileController(
        label=[mod.Label(text="R")], download_url="https://example.org/a.bin"
    )
    with pytest.raises(NotImplementedError):
        controller.put(io.BytesIO(CONTENT))


@pytest.mark.parametrize("mod", MODULES)
def test_remote_downloads_into_a_local_file(mod, http_server, tmp_path):
    """The transfer the distributions of a dataset need."""
    remote = mod.RemoteFileController(
        label=[mod.Label(text="R")], download_url=http_server
    )
    local = _local(mod, tmp_path / "downloaded.bin")
    local.put_from(remote)
    assert (tmp_path / "downloaded.bin").read_bytes() == CONTENT
