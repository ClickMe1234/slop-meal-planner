"""Validation for the application-data archive before a destructive restore."""

from __future__ import annotations

import posixpath
from pathlib import Path
import sys
import tarfile


def validate_data_archive(archive: Path) -> None:
    """Require a readable archive containing only safe application paths."""

    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            name = member.name
            if "\x00" in name or name.startswith("/") or any(part == ".." for part in name.split("/")):
                raise ValueError("archive contains an unsafe data path")
            if member.issym() or member.islnk():
                target = member.linkname
                if target.startswith("/") or any(part == ".." for part in target.split("/")):
                    raise ValueError("archive contains an unsafe link")
            if not (member.isdir() or member.isreg() or member.issym() or member.islnk()):
                raise ValueError("archive contains an unsupported file type")
            if posixpath.normpath(name).startswith("../"):
                raise ValueError("archive contains an unsafe data path")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m app.restore_validation <data.tar.gz>", file=sys.stderr)
        return 64
    try:
        validate_data_archive(Path(sys.argv[1]))
    except (OSError, tarfile.TarError, ValueError) as exc:
        print(f"Application data archive is unreadable or unsafe: {exc}", file=sys.stderr)
        return 66
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

