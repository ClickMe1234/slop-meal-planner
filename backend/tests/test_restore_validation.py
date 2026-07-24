from __future__ import annotations

import io
from pathlib import Path
import tarfile

import pytest

from app.restore_validation import validate_data_archive


def _archive(path: Path, name: str) -> None:
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.size = 4
        archive.addfile(member, io.BytesIO(b"data"))


def test_restore_archive_accepts_generated_relative_paths(tmp_path):
    archive = tmp_path / "data.tar.gz"
    _archive(archive, "./nested/file.txt")

    validate_data_archive(archive)


@pytest.mark.parametrize("name", ["../outside.txt", "/outside.txt", "nested/../../outside.txt"])
def test_restore_archive_rejects_traversal_and_absolute_paths(tmp_path, name: str):
    archive = tmp_path / "data.tar.gz"
    _archive(archive, name)

    with pytest.raises(ValueError, match="unsafe data path"):
        validate_data_archive(archive)
