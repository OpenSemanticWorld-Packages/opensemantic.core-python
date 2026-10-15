"""Download a CSV over HTTP through the file controllers.

A ``RemoteFile`` describes a file behind a URL; the controller for it reads the
bytes. Nothing here knows it is HTTP: the same two calls work for a file on
disk or on a wiki, because the controller is resolved from the entity's type.

Run from the package root::

    python examples/download_remote_file.py
"""

from pathlib import Path

from opensemantic.core import (
    Label,
    LocalFile,
    RemoteFile,
    get_file_controller,
)

CSV_URL = (
    "https://raw.githubusercontent.com/w3c/csvw/refs/heads/gh-pages/"
    "examples/dm-example-1/addresses.csv"
)
TARGET = Path(__file__).parent / "addresses.csv"


def main() -> None:
    # 1. The file as an entity: what it is, not how to read it.
    remote = RemoteFile(
        label=[Label(text="W3C CSVW example addresses")], download_url=CSV_URL
    )

    # 2. The controller that can read that entity, from the type registry.
    source = get_file_controller(remote)
    print(f"{type(source).__name__} reads {CSV_URL}")

    with source.get() as handle:
        content = handle.read().decode("utf-8")
    print(f"\n{content}")

    # 3. The same interface writes it, so a transfer is one call. ``put_from``
    #    reads the source and closes it.
    local = get_file_controller(
        LocalFile(label=[Label(text=TARGET.name)], local_path=str(TARGET))
    )
    local.put_from(source)
    print(f"Wrote {TARGET.stat().st_size} bytes to {TARGET}")


if __name__ == "__main__":
    main()
