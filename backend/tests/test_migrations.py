from __future__ import annotations

import ast
import json
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


def _run_alembic(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["MEAL_PLANNER_DATABASE_URL"] = _database_url(path)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
    )


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
    assert "0023_member_meal_groups (head)" in current.stdout
    assert len("0017_quarantine_urls") <= 32
    assert "recipe_publisher_tag" in _tables(database)

    # A full reverse and second replay catches migration ordering, hidden live
    # metadata dependencies, and SQLite-incompatible historical operations.
    _alembic(database, "downgrade", "base")
    assert _tables(database) == {"alembic_version"}
    _alembic(database, "upgrade", "head")
    assert "recipe_publisher_tag" in _tables(database)


def test_downgrade_refuses_split_meal_groups_without_mutating_data(tmp_path):
    database = tmp_path / "split-meal-downgrade.db"

    _alembic(database, "upgrade", "head")

    occurrence_rows = [
        ("occurrence-shared", "shared", "batch-shared"),
        ("occurrence-separate", "separate", "batch-separate"),
    ]

    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO meal_occurrence
                (id, created_at, updated_at, version, meal_plan_id, batch_id,
                 meal_date, meal_type, meal_group_key, component_slot, locked,
                 unplanned_allowance, guest_servings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    occurrence_id,
                    "2026-08-14T00:00:00+00:00",
                    "2026-08-14T00:00:00+00:00",
                    1,
                    "plan-1",
                    batch_id,
                    "2026-08-14",
                    "breakfast",
                    meal_group_key,
                    0,
                    0,
                    0,
                    0,
                )
                for occurrence_id, meal_group_key, batch_id in occurrence_rows
            ],
        )
        connection.commit()

    result = _run_alembic(database, "downgrade", "-1")

    assert result.returncode != 0
    assert "Cannot downgrade 0023_member_meal_groups" in result.stderr
    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(meal_occurrence)")
        }
        occurrences = connection.execute(
            "SELECT id, meal_group_key FROM meal_occurrence ORDER BY id"
        ).fetchall()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]

    assert "meal_group_key" in columns
    assert occurrences == [
        ("occurrence-separate", "separate"),
        ("occurrence-shared", "shared"),
    ]
    assert revision == "0023_member_meal_groups"


def test_upgrade_from_published_flow_table_revision_reconciles_branches(tmp_path):
    database = tmp_path / "published-flow-migration.db"
    _alembic(database, "upgrade", "0020_recipe_method_flow_tables")

    assert "recipe_method_table_snapshot" in _tables(database)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO household
                (id, name, timezone, created_at, updated_at, version)
            VALUES
                ('legacy-household', 'Legacy household', 'Europe/London',
                 '2026-08-09T00:00:00+00:00', '2026-08-09T00:00:00+00:00', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO app_user
                (id, household_id, username, password_hash, role, active,
                 must_change_password, ingredient_locale, method_view_preference,
                 measurement_system, method_tutorial_version_seen, member_id,
                 created_at, updated_at, version)
            VALUES
                ('legacy-user', 'legacy-household', 'legacy', 'unused', 'owner', 1,
                 0, 'uk', 'table', 'source', 0, NULL,
                 '2026-08-09T00:00:00+00:00', '2026-08-09T00:00:00+00:00', 1)
            """
        )
        connection.commit()

    _alembic(database, "upgrade", "head")

    assert "recipe_method_table_snapshot" not in _tables(database)
    with sqlite3.connect(database) as connection:
        session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(user_session)")
        }
        method_view_preference = connection.execute(
            "SELECT method_view_preference FROM app_user WHERE id = 'legacy-user'"
        ).fetchone()[0]
    assert "remember_me" in session_columns
    assert method_view_preference == "summary"


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


def test_upgrade_from_0018_migrates_custom_instructions_to_method_snapshot(tmp_path):
    database = tmp_path / "method-migration.db"
    _alembic(database, "upgrade", "0018_shopping_recipe_links")

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO household
                (id, name, timezone, created_at, updated_at, version)
            VALUES
                ('household-method', 'Method household', 'Europe/London',
                 '2026-08-08T00:00:00+00:00', '2026-08-08T00:00:00+00:00', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO recipe
                (id, household_id, title, eligibility, source_type, created_at, updated_at, version)
            VALUES
                ('recipe-method', 'household-method', 'Family soup', 'draft', 'custom',
                 '2026-08-08T00:00:00+00:00', '2026-08-08T00:00:00+00:00', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO recipe_version
                (id, recipe_id, version_number, title, yield_servings,
                 custom_instructions, created_at)
            VALUES
                ('version-method', 'recipe-method', 1, 'Family soup', 4,
                 'Simmer gently. Serve hot.', '2026-08-08T00:00:00+00:00')
            """
        )
        connection.commit()

    _alembic(database, "upgrade", "head")

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        snapshot = connection.execute(
            "SELECT * FROM recipe_method_snapshot WHERE recipe_version_id = 'version-method'"
        ).fetchone()
        assert snapshot is not None
        assert snapshot["source_kind"] == "custom"
        assert snapshot["source_text"] == "Simmer gently. Serve hot."
        assert json.loads(snapshot["source_blocks"])[0]["text"] == snapshot["source_text"]
        assert json.loads(snapshot["document"])["schema_version"] == 1
        assert json.loads(snapshot["coverage"])["unreviewed"] == 1


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
