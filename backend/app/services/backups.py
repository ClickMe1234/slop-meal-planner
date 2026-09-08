from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from ..errors import DomainError


_backup_lock = threading.Lock()


def backup_status() -> dict[str, object]:
    root = Path(os.getenv("BACKUP_ROOT", "/backups"))
    candidates: list[tuple[str, Path]] = []
    for tier in ("daily", "weekly", "monthly"):
        tier_dir = root / tier
        if not tier_dir.is_dir():
            continue
        candidates.extend((tier, item) for item in tier_dir.iterdir() if item.is_dir() and not item.name.startswith("."))
    if not candidates:
        return {"available": root.parent.exists(), "last_backup": None, "tier": None}
    tier, latest = max(candidates, key=lambda item: item[1].name)
    manifest: dict[str, str] = {}
    manifest_path = latest / "manifest.txt"
    if manifest_path.is_file():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                manifest[key] = value
    return {
        "available": True,
        "last_backup": manifest.get("created_at", latest.name),
        "tier": manifest.get("tier", tier),
        "application_version": manifest.get("application_version"),
        "schema_revision": manifest.get("schema_revision"),
    }


def create_backup() -> dict[str, object]:
    script = Path(os.getenv("BACKUP_SCRIPT_PATH", "/opt/meal-planner/backup.sh"))
    if not script.is_file():
        raise DomainError(
            "BACKUP_UNAVAILABLE",
            "The backup command is not installed in this application image.",
            503,
        )
    if not _backup_lock.acquire(blocking=False):
        raise DomainError("BACKUP_IN_PROGRESS", "A backup is already running.", 409)
    try:
        try:
            result = subprocess.run(
                ["sh", str(script)],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            raise DomainError("BACKUP_TIMEOUT", "The backup did not finish within five minutes.", 504) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            message = detail[-1] if detail else "The backup command failed."
            raise DomainError("BACKUP_FAILED", message[:500], 500)
        return backup_status()
    finally:
        _backup_lock.release()
