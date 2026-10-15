"""Download a CSV over HTTP through the file controllers.

A ``RemoteFile`` describes a file behind a URL and reads it: the name resolves
to the controller that implements the model, so there is nothing to wrap.
Nothing here knows it is HTTP either - the same calls work for a file on disk
or on a wiki.

Run from the package root::

    python examples/download_remote_file.py
"""

from pathlib import Path

from opensemantic.core import Label, LocalFile, RemoteFile

CSV_URL = (
    "https://raw.githubusercontent.com/w3c/csvw/refs/heads/gh-pages/"
    "examples/dm-example-1/addresses.csv"
)
TARGET = Path(__file__).parent / "addresses.csv"


def main() -> None:
    # 1. The file as an entity. RemoteFile is the controller that implements
    #    the model, so it both describes the file and reads it.
    source = RemoteFile(
        label=[Label(text="W3C CSVW example addresses")], download_url=CSV_URL
    )
    print(f"{type(source).__name__} reads {CSV_URL}")

    with source.get() as handle:
        content = handle.read().decode("utf-8")
    print(f"\n{content}")

    # 2. Every file controller answers to the same two calls, so a transfer is
    #    one of them. put_from reads the source and closes it.
    local = LocalFile(label=[Label(text=TARGET.name)], local_path=str(TARGET))
    local.put_from(source)
    print(f"Wrote {TARGET.stat().st_size} bytes to {TARGET}")


if __name__ == "__main__":
    main()
