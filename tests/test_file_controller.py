"""Tests for the file controllers.

Covers the local, in-memory and remote implementations, the transfer helpers
between them, and the registry lookup that lets a caller materialize a file
entity without knowing the concrete controller.

The models are imported inside a fixture, as ``general_test.py`` imports inside
its tests. Both layers are imported for every case: the lookup has to pick the
controller of the entity's own layer, and with only one layer loaded there is
nothing in the other registry for it to pick wrongly.

Run with ``--no-cov`` locally. Enabling coverage in a checkout that has several
source trees on the path breaks the import of ``oold`` itself with a metaclass
conflict, which has nothing to do with these tests.
"""

import importlib
import io
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

CONTENT = b"the file content"


@pytest.fixture(params=["v2", "v1"])
def mod(request):
    # both, always: the opposing registry has to be populated for the
    # layer-selection tests to mean anything
    v2 = importlib.import_module("opensemantic.core")
    v1 = importlib.import_module("opensemantic.core.v1")
    return v1 if request.param == "v1" else v2


def _local(mod, path, text="Test File"):
    return mod.LocalFileController(label=[mod.Label(text=text)], local_path=str(path))


def test_local_put_and_get(mod, tmp_path):
    controller = _local(mod, tmp_path / "a.bin")
    controller.put(io.BytesIO(CONTENT))
    assert (tmp_path / "a.bin").read_bytes() == CONTENT
    with controller.get() as f:
        assert f.read() == CONTENT


def test_local_put_accepts_a_text_stream(mod, tmp_path):
    controller = _local(mod, tmp_path / "a.txt")
    controller.put(io.StringIO("text content"))
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "text content"


def test_local_delete(mod, tmp_path):
    path = tmp_path / "a.bin"
    controller = _local(mod, path)
    controller.put(io.BytesIO(CONTENT))
    assert path.exists()
    controller.delete()
    assert not path.exists()
    controller.delete()  # a missing file is not an error


def test_local_without_path_fails_clearly(mod):
    controller = mod.LocalFileController(label=[mod.Label(text="No path")])
    with pytest.raises(ValueError, match="local_path"):
        controller.get()


def test_put_from_copies_between_controllers(mod, tmp_path):
    source = _local(mod, tmp_path / "source.bin")
    source.put(io.BytesIO(CONTENT))

    memory = mod.InMemoryController(label=[mod.Label(text="Stream")])
    memory.put_from(source)
    assert memory.get().read() == CONTENT


def test_get_to_copies_between_controllers(mod, tmp_path):
    source = _local(mod, tmp_path / "source.bin")
    source.put(io.BytesIO(CONTENT))
    target = _local(mod, tmp_path / "target.bin")

    source.get_to(target)
    assert (tmp_path / "target.bin").read_bytes() == CONTENT


# -- in memory --


def test_in_memory_round_trip(mod):
    memory = mod.InMemoryController(label=[mod.Label(text="Stream")])
    memory.put(io.BytesIO(CONTENT))
    assert memory.get().read() == CONTENT
    assert memory.get().read() == CONTENT  # re-readable


def test_in_memory_survives_a_closing_reader(mod):
    """``with controller.get()`` is how the transfer helpers read."""
    memory = mod.InMemoryController(label=[mod.Label(text="Stream")])
    memory.put(io.BytesIO(CONTENT))
    with memory.get() as f:
        assert f.read() == CONTENT
    with memory.get() as f:
        assert f.read() == CONTENT


def test_in_memory_put_replaces_the_content(mod):
    memory = mod.InMemoryController(label=[mod.Label(text="Stream")])
    memory.put(io.BytesIO(b"a longer first content"))
    memory.put(io.BytesIO(CONTENT))
    assert memory.get().read() == CONTENT


def test_in_memory_put_accepts_a_text_stream(mod):
    memory = mod.InMemoryController(label=[mod.Label(text="Stream")])
    memory.put(io.StringIO("text content"))
    assert memory.get().read() == b"text content"


def test_text_is_the_same_bytes_whichever_controller_writes_it(mod, tmp_path):
    """A transfer between the two must not depend on the locale encoding."""
    text = "Messgroesse äöüß"
    local = _local(mod, tmp_path / "a.txt")
    memory = mod.InMemoryController(label=[mod.Label(text="Stream")])

    local.put(io.StringIO(text))
    memory.put(io.StringIO(text))

    assert (tmp_path / "a.txt").read_bytes() == memory.get().read()
    assert memory.get().read().decode("utf-8") == text


def test_in_memory_is_a_transfer_source(mod, tmp_path):
    memory = mod.InMemoryController(label=[mod.Label(text="Stream")])
    memory.put(io.BytesIO(CONTENT))
    target = _local(mod, tmp_path / "target.bin")

    memory.get_to(target)

    assert (tmp_path / "target.bin").read_bytes() == CONTENT
    assert memory.get().read() == CONTENT  # the source is still readable


def test_in_memory_is_constructible_from_a_local_file(mod, tmp_path):
    """Design rule 3: requested explicitly, built from the data model."""
    entity = mod.LocalFile(
        label=[mod.Label(text="Named")], local_path=str(tmp_path / "a.bin")
    )
    memory = mod.InMemoryController(entity)
    assert isinstance(memory, mod.InMemoryController)
    assert memory.local_path == str(tmp_path / "a.bin")


def test_from_other_copies_common_fields(mod, tmp_path):
    entity = mod.LocalFile(
        label=[mod.Label(text="Named")], local_path=str(tmp_path / "a.bin")
    )
    controller = mod.LocalFileController.from_other(entity)
    assert isinstance(controller, mod.LocalFileController)
    assert controller.label[0].text == "Named"
    assert controller.local_path == str(tmp_path / "a.bin")


# -- registry lookup --


def test_lookup_returns_the_local_controller(mod, tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(CONTENT)
    entity = mod.LocalFile(label=[mod.Label(text="A")], local_path=str(path))

    controller = mod.get_file_controller(entity)

    assert isinstance(controller, mod.LocalFileController)
    with controller.get() as f:
        assert f.read() == CONTENT


def test_lookup_returns_the_remote_controller(mod):
    entity = mod.RemoteFile(
        label=[mod.Label(text="R")], download_url="https://example.org/a.bin"
    )
    assert isinstance(mod.get_file_controller(entity), mod.RemoteFileController)


def test_lookup_picks_the_controller_of_the_entity_version(mod):
    """v1 and v2 share type IRIs, so the entity's own layer decides."""
    entity = mod.LocalFile(label=[mod.Label(text="A")], local_path="/tmp/a.bin")
    controller = mod.get_file_controller(entity)
    assert type(controller).__module__ == mod.LocalFileController.__module__


def test_lookup_skips_the_in_memory_controller(mod):
    """It reuses the local file model without being registered for it."""
    entity = mod.LocalFile(label=[mod.Label(text="A")], local_path="/tmp/a.bin")
    assert not isinstance(mod.get_file_controller(entity), mod.InMemoryController)


def test_lookup_returns_none_for_a_file_without_content_access(mod):
    """A plain File is neither local nor remote, so nothing can read it."""
    assert mod.get_file_controller(mod.File(label=[mod.Label(text="F")])) is None


def test_lookup_passes_through_a_controller(mod, tmp_path):
    controller = _local(mod, tmp_path / "a.bin")
    assert mod.get_file_controller(controller) is controller


def test_lookup_applies_kwargs_when_building(mod, tmp_path):
    entity = mod.LocalFile(label=[mod.Label(text="A")], local_path="/tmp/a.bin")
    controller = mod.get_file_controller(entity, local_path=str(tmp_path / "b.bin"))
    assert controller.local_path == str(tmp_path / "b.bin")


def test_lookup_applies_kwargs_to_a_controller_it_was_given(mod, tmp_path):
    """The path that has to carry a session or credentials."""
    controller = _local(mod, tmp_path / "a.bin")

    updated = mod.get_file_controller(controller, local_path=str(tmp_path / "b.bin"))

    assert updated.local_path == str(tmp_path / "b.bin")
    # the caller keeps the controller it handed in, pointing where it did
    assert controller.local_path == str(tmp_path / "a.bin")


def test_lookup_drops_a_kwarg_the_controller_does_not_declare(mod, tmp_path):
    """A caller offers what it has without knowing which controller answers."""
    entity = mod.LocalFile(label=[mod.Label(text="A")], local_path=str(tmp_path / "a"))

    controller = mod.get_file_controller(entity, osw="SESSION")

    assert isinstance(controller, mod.LocalFileController)
    assert not hasattr(controller, "osw")


def test_lookup_accepts_a_foreign_controller(mod):
    """Anything answering to get/put is already a controller."""

    class Foreign:
        type = ["Category:OSWSomethingElse"]

        def get(self):
            return io.BytesIO(CONTENT)

        def put(self, file, **kwargs):
            pass

    foreign = Foreign()
    assert mod.get_file_controller(foreign) is foreign


def test_lookup_hands_a_foreign_controller_everything_it_was_given(mod):
    """It declares no fields, so nothing can be filtered out for it."""

    class Foreign:
        type = ["Category:OSWSomethingElse"]

        def get(self):
            return io.BytesIO(CONTENT)

        def put(self, file, **kwargs):
            pass

    foreign = mod.get_file_controller(Foreign(), osw="SESSION")

    assert foreign.osw == "SESSION"


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


def test_remote_get_downloads(mod, http_server):
    controller = mod.RemoteFileController(
        label=[mod.Label(text="R")], download_url=http_server
    )
    with controller.get() as f:
        assert f.read() == CONTENT


def test_remote_get_falls_back_to_access_url(mod, http_server):
    controller = mod.RemoteFileController(
        label=[mod.Label(text="R")], access_url=http_server
    )
    with controller.get() as f:
        assert f.read() == CONTENT


def test_remote_accepts_an_upper_case_scheme(mod, http_server):
    """RFC 3986: the scheme is case-insensitive."""
    controller = mod.RemoteFileController(
        label=[mod.Label(text="R")],
        download_url=http_server.replace("http://", "HTTP://", 1),
    )
    with controller.get() as f:
        assert f.read() == CONTENT


def test_remote_without_url_fails_clearly(mod):
    controller = mod.RemoteFileController(label=[mod.Label(text="R")])
    with pytest.raises(ValueError, match="download_url"):
        controller.get()


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "FILE:///etc/passwd", "/etc/passwd"]
)
def test_remote_rejects_a_non_http_url(mod, url):
    controller = mod.RemoteFileController(label=[mod.Label(text="R")], download_url=url)
    with pytest.raises(ValueError, match="scheme"):
        controller.get()


def test_remote_put_is_not_generic(mod):
    controller = mod.RemoteFileController(
        label=[mod.Label(text="R")], download_url="https://example.org/a.bin"
    )
    with pytest.raises(NotImplementedError):
        controller.put(io.BytesIO(CONTENT))


def test_remote_downloads_into_a_local_file(mod, http_server, tmp_path):
    """The transfer the distributions of a dataset need."""
    remote = mod.RemoteFileController(
        label=[mod.Label(text="R")], download_url=http_server
    )
    local = _local(mod, tmp_path / "downloaded.bin")
    local.put_from(remote)
    assert (tmp_path / "downloaded.bin").read_bytes() == CONTENT


def test_resolve_path_is_a_method_not_a_property(mod, tmp_path):
    """A property named like a field wins over it, hiding the field's value."""
    controller = _local(mod, tmp_path / "a.bin")

    assert controller.resolve_path() == tmp_path / "a.bin"
    assert not isinstance(getattr(type(controller), "path", None), property)


def test_resolve_path_without_a_file_fails_clearly(mod):
    controller = mod.LocalFileController(label=[mod.Label(text="No path")])
    with pytest.raises(ValueError, match="local_path"):
        controller.resolve_path()
