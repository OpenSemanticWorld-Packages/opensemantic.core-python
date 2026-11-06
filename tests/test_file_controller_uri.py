"""Tests for the uri property of the file controllers.

The uri is the location of the file in the URI scheme of its storage backend,
derived on every access and never stored.
"""

import importlib
import io
import json
from pathlib import Path
from typing import IO, Any, Dict

import pytest

from opensemantic.core._file_controller_mixin import FileControllerMixin


@pytest.fixture(params=["v2", "v1"])
def mod(request):
    v2 = importlib.import_module("opensemantic.core")
    v1 = importlib.import_module("opensemantic.core.v1")
    return v1 if request.param == "v1" else v2


def _dump(controller):
    # v1 models have dict(), v2 models model_dump()
    dump = getattr(controller, "model_dump", None) or controller.dict
    return dump()


def test_a_controller_that_predates_uri_still_works():
    """uri is deliberately not abstract: pydantic v1's ModelMetaclass extends
    ABCMeta, so an abstract property would break every controller outside this
    package that does not know about it yet."""

    class ControllerWithoutUri(FileControllerMixin):
        def get(self) -> IO:
            pass

        def put(self, file: IO, **kwargs: Dict[str, Any]) -> None:
            pass

    assert ControllerWithoutUri().uri is None


def test_a_v1_controller_that_predates_uri_still_works(mod):
    class ControllerWithoutUri(FileControllerMixin, mod.File):
        def get(self) -> IO:
            pass

        def put(self, file: IO, **kwargs: Dict[str, Any]) -> None:
            pass

    controller = ControllerWithoutUri(label=[mod.Label(text="x")])
    assert controller.uri is None


def test_local_uri_is_a_file_url(mod, tmp_path):
    path = tmp_path / "test.txt"
    controller = mod.LocalFileController(
        label=[mod.Label(text="x")], local_path=str(path)
    )

    assert controller.uri == Path(path).absolute().as_uri()
    assert controller.uri.startswith("file:///")


def test_local_uri_is_absolute_for_a_relative_path(mod, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = mod.LocalFileController(
        label=[mod.Label(text="x")], local_path="test.txt"
    )

    assert controller.uri == (Path.cwd() / "test.txt").as_uri()


def test_local_uri_escapes_reserved_characters(mod, tmp_path):
    controller = mod.LocalFileController(
        label=[mod.Label(text="x")], local_path=str(tmp_path / "a file.txt")
    )

    assert controller.uri.endswith("/a%20file.txt")


def test_local_uri_is_none_without_a_path(mod):
    assert mod.LocalFileController(label=[mod.Label(text="x")]).uri is None


def test_in_memory_uri_is_none(mod):
    assert mod.InMemoryController().uri is None


def test_remote_uri_is_the_download_url(mod):
    url = "https://example.org/files/a.bin"
    controller = mod.RemoteFileController(label=[mod.Label(text="x")], download_url=url)

    assert controller.uri == url


def test_remote_uri_falls_back_to_the_access_url(mod):
    url = "https://example.org/files/a.bin"
    controller = mod.RemoteFileController(label=[mod.Label(text="x")], access_url=url)

    assert controller.uri == url


def test_remote_uri_is_none_without_a_url(mod):
    assert mod.RemoteFileController(label=[mod.Label(text="x")]).uri is None


def test_uri_is_not_serialized(mod, tmp_path):
    controller = mod.LocalFileController(
        label=[mod.Label(text="x")], local_path=str(tmp_path / "a.txt")
    )
    dump_json = getattr(controller, "model_dump_json", None) or controller.json

    assert controller.uri is not None
    assert "uri" not in _dump(controller)
    assert "uri" not in json.loads(dump_json())


def test_uri_is_not_in_the_json_schema(mod):
    cls = mod.LocalFileController
    schema = (getattr(cls, "model_json_schema", None) or cls.schema)()

    assert "uri" not in schema.get("properties", {})


def test_the_controller_is_unchanged_by_reading_uri(mod, tmp_path):
    controller = mod.LocalFileController(
        label=[mod.Label(text="x")], local_path=str(tmp_path / "a.txt")
    )
    before = _dump(controller)
    controller.uri
    controller.put(io.BytesIO(b"x"))
    assert _dump(controller) == before
