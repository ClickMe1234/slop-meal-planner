from __future__ import annotations

import ast
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = BACKEND_ROOT / "migrations" / "versions"


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _alembic(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["MEAL_PLANNER_DATABASE_URL"] = _database_url(path)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(arguments)} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }


def test_clean_database_replays_to_head_without_model_drift(tmp_path):
    database = tmp_path / "clean-migration.db"

    _alembic(database, "upgrade", "head")
    check = _alembic(database, "check")
    current = _alembic(database, "current")

    assert "No new upgrade operations detected" in check.stdout
    assert "0010_pantry_use_soon (head)" in current.stdout
    assert "recipe_publisher_tag" in _tables(database)

    # A full reverse and second replay catches migration ordering, hidden live
    # metadata dependencies, and SQLite-incompatible historical operations.
    _alembic(database, "downgrade", "base")
    assert _tables(database) == {"alembic_version"}
    _alembic(database, "upgrade", "head")
    assert "recipe_publisher_tag" in _tables(database)


def test_upgrade_from_0007_preserves_existing_recipe_and_marks_backfill(tmp_path):
    database = tmp_path / "upgrade-migration.db"
    _alembic(database, "upgrade", "0007_shopping_display_units")

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO household
                (id, name, timezone, created_at, updated_at, version)
            VALUES
                ('household-1', 'Migration household', 'Europe/London',
                 '2026-07-17T00:00:00+00:00', '2026-07-17T00:00:00+00:00', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO recipe
                (id, household_id, title, eligibility, source_type, source_url,
                 publisher, image_url, archived_at, created_at, updated_at, version)
            VALUES
                ('recipe-1', 'household-1', 'Existing soup', 'draft', 'url',
                 'https://www.bbcgoodfood.com/recipes/existing-soup', 'Good Food',
                 NULL, NULL, '2026-07-17T00:00:00+00:00',
                 '2026-07-17T00:00:00+00:00', 3)
            """
        )
        connection.commit()

    _alembic(database, "upgrade", "head")

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        recipe = connection.execute(
            "SELECT * FROM recipe WHERE id = 'recipe-1'"
        ).fetchone()
        assert recipe is not None
        assert recipe["title"] == "Existing soup"
        assert recipe["source_url"].endswith("/existing-soup")
        assert recipe["version"] == 3
        assert recipe["publisher_metadata_status"] == "pending"
        assert recipe["publisher_metadata_attempts"] == 0


def test_historical_migrations_do_not_import_live_application_models():
    violations: list[str] = []
    for migration in sorted(MIGRATIONS.glob("*.py")):
        source = migration.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(migration))
        for forbidden in ("create_all(", "drop_all(", "Base.metadata"):
            if forbidden in source:
                violations.append(f"{migration.name} contains {forbidden}")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                node.module == "app" or (node.module or "").startswith("app.")
            ):
                violations.append(f"{migration.name}:{node.lineno} imports {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app" or alias.name.startswith("app."):
                        violations.append(f"{migration.name}:{node.lineno} imports {alias.name}")

    assert violations == []
