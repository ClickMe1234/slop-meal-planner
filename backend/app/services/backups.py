from __future__ import annotations

import os
from contextlib import contextmanager
import fcntl
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

from ..errors import DomainError


def _lock_path() -> Path:
    root = Path(os.getenv("BACKUP_ROOT", "/backups"))
    return Path(os.getenv("BACKUP_LOCK_FILE", str(root / ".backup.lock")))


@contextmanager
def _backup_lock() -> Iterator[None]:
    """Acquire the same advisory lock used by maintenance shell scripts."""

    path = _lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+")
    except OSError as exc:
        raise DomainError(
            "BACKUP_UNAVAILABLE",
            "The backup lock storage is not available.",
            503,
        ) from exc
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DomainError("BACKUP_IN_PROGRESS", "A backup or restore is already running.", 409) from exc
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _runtime_available(script: Path, root: Path) -> bool:
    required_commands = ("pg_dump", "pg_restore", "psql", "tar", "sha256sum")
    return (
        script.is_file()
        and root.is_dir()
        and os.access(root, os.R_OK | os.W_OK | os.X_OK)
        and all(shutil.which(command) for command in required_commands)
    )


def backup_status() -> dict[str, object]:
    root = Path(os.getenv("BACKUP_ROOT", "/backups"))
    script = Path(os.getenv("BACKUP_SCRIPT_PATH", "/opt/meal-planner/backup.sh"))
    runtime_available = _runtime_available(script, root)
    candidates: list[tuple[str, Path]] = []
    for tier in ("daily", "weekly", "monthly"):
        tier_dir = root / tier
        if not tier_dir.is_dir():
            continue
        candidates.extend((tier, item) for item in tier_dir.iterdir() if item.is_dir() and not item.name.startswith("."))
    if not candidates:
        return {
            "available": runtime_available,
            "runtime_available": runtime_available,
            "last_backup": None,
            "tier": None,
        }
    tier, latest = max(candidates, key=lambda item: item[1].name)
    manifest: dict[str, str] = {}
    manifest_path = latest / "manifest.txt"
    if manifest_path.is_file():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                manifest[key] = value
    return {
        "available": runtime_available,
        "runtime_available": runtime_available,
        "last_backup": manifest.get("created_at", latest.name),
        "tier": manifest.get("tier", tier),
        "application_version": manifest.get("application_version"),
        "schema_revision": manifest.get("schema_revision"),
    }


def create_backup() -> dict[str, object]:
    script = Path(os.getenv("BACKUP_SCRIPT_PATH", "/opt/meal-planner/backup.sh"))
    root = Path(os.getenv("BACKUP_ROOT", "/backups"))
    if not _runtime_available(script, root):
        raise DomainError(
            "BACKUP_UNAVAILABLE",
            "The backup runtime or storage is not available in this application image.",
            503,
        )
    with _backup_lock():
        try:
            environment = os.environ.copy()
            environment["BACKUP_LOCK_HELD"] = "1"
            result = subprocess.run(
                ["sh", str(script)],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise DomainError("BACKUP_TIMEOUT", "The backup did not finish within five minutes.", 504) from exc
        if result.returncode != 0:
            raise DomainError("BACKUP_FAILED", "The backup command failed; inspect the maintenance logs.", 500)
        return backup_status()
