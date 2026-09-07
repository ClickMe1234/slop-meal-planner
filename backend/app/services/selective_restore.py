"""Preview and selectively merge household data from a PostgreSQL backup.

The normal disaster-recovery restore intentionally replaces the application
database.  This module provides the safer migration-shaped alternative: load
the custom-format dump into a temporary database, inspect it, and merge only
the requested household domains into the current household.  Session tokens,
integration credentials, jobs, and other operational state are deliberately
never copied.
"""

from __future__ import annotations

import os
import re
import hashlib
import logging
import secrets
import subprocess
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, func, or_, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from ..discovery.errors import InvalidUrlError
from ..discovery.urls import canonicalize_url
from ..errors import DomainError
from .backups import _backup_lock
from ..models import (
    FoodAlias,
    FoodNutrient,
    FoodRecord,
    Household,
    HouseholdFoodUnitConversion,
    HouseholdMealGroupAssignment,
    HouseholdMember,
    IngredientNameEquivalent,
    IngredientNameOverride,
    MealAllocation,
    MealBatch,
    MealOccurrence,
    MealPlan,
    NutritionCalculation,
    PantryLot,
    PantryReservation,
    PantryTransaction,
    PlanStatus,
    PortionAllocation,
    Recipe,
    RecipeIngredient,
    RecipeMealType,
    RecipeMethodSnapshot,
    RecipePublisherTag,
    RecipeVersion,
    Restriction,
    SavedFood,
    ShoppingItem,
    ShoppingList,
    TargetProfile,
    User,
)


ARCHIVE_RE = re.compile(r"^(daily|weekly|monthly)/([0-9]{8}-[0-9]{6})$")
RESTORE_LOCK = threading.Lock()
LOGGER = logging.getLogger(__name__)

COMPONENTS = (
    "household",
    "users",
    "recipes",
    "ingredients",
    "pantry",
    "shopping",
    "plans",
)

COMPONENT_INFO: dict[str, dict[str, str]] = {
    "household": {
        "label": "Household settings",
        "description": "People, dietary preferences, targets and household naming rules.",
    },
    "users": {
        "label": "User accounts",
        "description": "Non-session user accounts. Existing accounts are kept when usernames match.",
    },
    "recipes": {
        "label": "Recipes",
        "description": "Saved recipes, versions, ingredients, tags and nutrition calculations.",
    },
    "ingredients": {
        "label": "Ingredients & nutrition",
        "description": "Saved foods, nutrition records, ingredient aliases and confirmed unit mappings.",
    },
    "pantry": {
        "label": "Pantry",
        "description": "Pantry quantities, expiry flags and pantry movement history.",
    },
    "shopping": {
        "label": "Shopping lists",
        "description": "Shopping lists, checked states and manually added items.",
    },
    "plans": {
        "label": "Meal plans",
        "description": "Plans, batches, meal occurrences and member portions.",
    },
}

MODEL_BY_TABLE = {
    model.__tablename__: model
    for model in (
        Household,
        User,
        IngredientNameEquivalent,
        IngredientNameOverride,
        HouseholdMember,
        HouseholdMealGroupAssignment,
        TargetProfile,
        MealAllocation,
        Restriction,
        Recipe,
        RecipeMealType,
        RecipePublisherTag,
        RecipeVersion,
        RecipeIngredient,
        RecipeMethodSnapshot,
        FoodRecord,
        FoodNutrient,
        HouseholdFoodUnitConversion,
        SavedFood,
        FoodAlias,
        NutritionCalculation,
        MealPlan,
        MealBatch,
        MealOccurrence,
        PortionAllocation,
        PantryLot,
        PantryTransaction,
        PantryReservation,
        ShoppingList,
        ShoppingItem,
    )
}


@dataclass(frozen=True)
class ArchiveFiles:
    path: Path
    relative_path: str
    tier: str
    timestamp: str
    manifest: dict[str, str]
    database_dump: bool
    data_archive: bool
    checksums: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "archive": self.relative_path,
            "tier": self.tier,
            "timestamp": self.timestamp,
            "manifest": self.manifest,
            "files": {
                "database_dump": self.database_dump,
                "data_archive": self.data_archive,
                "checksums": self.checksums,
            },
            "selective_restore_available": self.database_dump,
        }


@dataclass
class SourceBundle:
    household: dict[str, Any]
    tables: dict[str, list[dict[str, Any]]]


def _trace_id() -> str:
    """Return a short non-sensitive identifier for operator diagnostics."""

    return uuid.uuid4().hex[:12]


def _backup_root() -> Path:
    return Path(os.getenv("BACKUP_ROOT", "/backups")).resolve()


def _relative_archive(value: str) -> tuple[str, str, str]:
    match = ARCHIVE_RE.fullmatch(value.strip().replace("\\", "/"))
    if not match:
        raise DomainError(
            "INVALID_BACKUP_PATH",
            "Choose a daily, weekly or monthly backup folder.",
            422,
        )
    return match.group(1), match.group(2), f"{match.group(1)}/{match.group(2)}"


def resolve_archive(value: str) -> ArchiveFiles:
    tier, timestamp, relative = _relative_archive(value)
    root = _backup_root()
    path = (root / tier / timestamp).resolve()
    if root not in path.parents or not path.is_dir():
        raise DomainError("BACKUP_NOT_FOUND", "That backup folder is not available on this installation.", 404)

    manifest: dict[str, str] = {}
    manifest_path = path / "manifest.txt"
    if manifest_path.is_file():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            key, separator, parsed = line.partition("=")
            if separator:
                manifest[key] = parsed
    return ArchiveFiles(
        path=path,
        relative_path=relative,
        tier=tier,
        timestamp=timestamp,
        manifest=manifest,
        database_dump=(path / "database.dump").is_file(),
        data_archive=(path / "data.tar.gz").is_file(),
        checksums=(path / "SHA256SUMS").is_file(),
    )


def verify_archive_checksums(archive: ArchiveFiles) -> None:
    checksum_path = archive.path / "SHA256SUMS"
    if not checksum_path.is_file():
        raise DomainError(
            "BACKUP_CHECKSUM_MISSING",
            "This backup has no checksum manifest and cannot be restored.",
            422,
        )
    expected: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?([A-Za-z0-9._-]+)", line.strip())
        if match:
            expected[match.group(2)] = match.group(1).lower()
    for name in ("database.dump", "data.tar.gz", "manifest.txt"):
        path = archive.path / name
        if not path.is_file() or name not in expected:
            raise DomainError(
                "BACKUP_CHECKSUM_INCOMPLETE",
                f"The backup checksum manifest does not cover {name}.",
                422,
            )
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if not secrets.compare_digest(digest.hexdigest(), expected[name]):
            raise DomainError(
                "BACKUP_CHECKSUM_FAILED",
                f"The backup failed integrity verification for {name}.",
                422,
            )


def list_archives() -> list[dict[str, Any]]:
    root = _backup_root()
    if not root.is_dir():
        return []
    archives: list[dict[str, Any]] = []
    for tier in ("daily", "weekly", "monthly"):
        tier_dir = root / tier
        if not tier_dir.is_dir():
            continue
        for folder in tier_dir.iterdir():
            if not folder.is_dir() or not re.fullmatch(r"[0-9]{8}-[0-9]{6}", folder.name):
                continue
            archive = resolve_archive(f"{tier}/{folder.name}")
            if archive.database_dump:
                archives.append(archive.as_dict())
    return sorted(archives, key=lambda item: item["timestamp"], reverse=True)


def _postgres_url() -> URL:
    url = make_url(get_settings().database_url)
    if not url.get_backend_name().startswith("postgresql"):
        raise DomainError(
            "RESTORE_UNAVAILABLE",
            "Selective restore requires the PostgreSQL application database.",
            503,
        )
    return url


def _postgres_environment(url: URL, database: str) -> dict[str, str]:
    environment = os.environ.copy()
    if url.host:
        environment["PGHOST"] = url.host
    if url.port:
        environment["PGPORT"] = str(url.port)
    if url.username:
        environment["PGUSER"] = url.username
    if url.password is not None:
        environment["PGPASSWORD"] = url.password
    environment["PGDATABASE"] = database
    sslmode = url.query.get("sslmode")
    if sslmode:
        environment["PGSSLMODE"] = sslmode
    return environment


class _TemporaryDatabase:
    def __init__(self, dump: Path):
        self.dump = dump
        self.name = f"slop_restore_{uuid.uuid4().hex[:20]}"
        self.url = _postgres_url()
        self.engine = None
        self.session_factory = None
        self.session: Session | None = None
        self.created = False

    def __enter__(self) -> Session:
        maintenance_url = self.url.set(database="postgres")
        maintenance_engine = create_engine(maintenance_url, pool_pre_ping=True)
        try:
            with maintenance_engine.connect() as connection:
                connection = connection.execution_options(isolation_level="AUTOCOMMIT")
                connection.execute(text(f'CREATE DATABASE "{self.name}"'))
                self.created = True
        except Exception as exc:
            raise DomainError(
                "RESTORE_DATABASE_PERMISSION",
                "The PostgreSQL account needs permission to create a temporary database for selective restore.",
                503,
            ) from exc
        finally:
            try:
                maintenance_engine.dispose()
            except Exception:
                if self.created:
                    self.close()
                raise
        try:
            result = subprocess.run(
                [
                    "pg_restore",
                    "--dbname",
                    self.name,
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    str(self.dump),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
                env=_postgres_environment(self.url, self.name),
            )
            if result.returncode != 0:
                raise DomainError(
                    "RESTORE_ARCHIVE_INVALID",
                    "The database archive could not be opened.",
                    422,
                )

            backend_dir = Path(__file__).resolve().parents[2]
            migration_environment = _postgres_environment(self.url, self.name)
            migration_environment["MEAL_PLANNER_DATABASE_URL"] = self.url.set(
                database=self.name
            ).render_as_string(hide_password=False)
            migration = subprocess.run(
                ["alembic", "-c", "alembic.ini", "upgrade", "head"],
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
                cwd=backend_dir,
                env=migration_environment,
            )
            if migration.returncode != 0:
                raise DomainError(
                    "RESTORE_SCHEMA_UNSUPPORTED",
                    "The backup schema could not be upgraded for inspection.",
                    422,
                )

            self.engine = create_engine(self.url.set(database=self.name), pool_pre_ping=True)
            self.session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
            self.session = self.session_factory()
            return self.session
        except subprocess.TimeoutExpired as exc:
            raise DomainError(
                "RESTORE_TIMEOUT",
                "The backup inspection timed out before it completed.",
                504,
            ) from exc
        except DomainError:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise DomainError(
                "RESTORE_UNAVAILABLE",
                "The backup inspection runtime is unavailable.",
                503,
            ) from exc
        except Exception as exc:
            raise DomainError(
                "RESTORE_UNAVAILABLE",
                "The backup inspection could not be prepared.",
                503,
            ) from exc
        finally:
            # __enter__ is not paired with __exit__ when setup raises.  Always
            # drop a database which has already been created, including a
            # timeout during pg_restore or migration.
            if self.session is None and self.created:
                self.close()

    def close(self) -> None:
        if self.session is not None:
            try:
                self.session.rollback()
            finally:
                self.session.close()
                self.session = None
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None
        if self.created:
            try:
                subprocess.run(
                    ["dropdb", "--if-exists", "--force", self.name],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=_postgres_environment(self.url, "postgres"),
                )
            except (OSError, subprocess.TimeoutExpired):
                LOGGER.warning("Temporary restore database cleanup failed", extra={"restore_db": self.name})
            finally:
                self.created = False

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def _value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _row_data(row: Any) -> dict[str, Any]:
    return {column.name: _value(getattr(row, column.name)) for column in row.__table__.columns}


def _rows(db: Session, model: Any, *criteria: Any) -> list[dict[str, Any]]:
    return [_row_data(row) for row in db.scalars(select(model).where(*criteria)).all()]


def _id_set(rows: Iterable[dict[str, Any]]) -> set[str]:
    return {row["id"] for row in rows}


def _load_source_bundle(db: Session, source_household_id: str | None) -> SourceBundle:
    households = db.scalars(select(Household).order_by(Household.created_at, Household.id)).all()
    if not households:
        raise DomainError("BACKUP_EMPTY", "The backup does not contain a household.", 422)
    household = next((item for item in households if item.id == source_household_id), None) if source_household_id else households[0]
    if household is None:
        raise DomainError("BACKUP_HOUSEHOLD_NOT_FOUND", "The selected household is not in that backup.", 422)
    household_id = household.id

    tables: dict[str, list[dict[str, Any]]] = {
        "household": [_row_data(household)],
        "household_member": _rows(db, HouseholdMember, HouseholdMember.household_id == household_id),
        "household_meal_group_assignment": _rows(
            db,
            HouseholdMealGroupAssignment,
            HouseholdMealGroupAssignment.household_id == household_id,
        ),
        "ingredient_name_equivalent": [_row_data(row) for row in db.scalars(select(IngredientNameEquivalent)).all()],
        "ingredient_name_override": _rows(db, IngredientNameOverride, IngredientNameOverride.household_id == household_id),
        "app_user": _rows(db, User, User.household_id == household_id),
        "target_profile": [],
        "meal_allocation": [],
        "restriction": [],
        "recipe": _rows(db, Recipe, Recipe.household_id == household_id),
        "recipe_meal_type": [],
        "recipe_publisher_tag": [],
        "recipe_version": [],
        "recipe_ingredient": [],
        "recipe_method_snapshot": [],
        "nutrition_calculation": [],
        "food_record": [],
        "food_nutrient": [],
        "household_food_unit_conversion": _rows(
            db,
            HouseholdFoodUnitConversion,
            HouseholdFoodUnitConversion.household_id == household_id,
        ),
        "saved_food": _rows(db, SavedFood, SavedFood.household_id == household_id),
        "food_alias": _rows(db, FoodAlias, FoodAlias.household_id == household_id),
        "meal_plan": _rows(db, MealPlan, MealPlan.household_id == household_id),
        "meal_batch": [],
        "meal_occurrence": [],
        "portion_allocation": [],
        "pantry_lot": _rows(db, PantryLot, PantryLot.household_id == household_id),
        "pantry_transaction": [],
        "pantry_reservation": [],
        "shopping_list": _rows(db, ShoppingList, ShoppingList.household_id == household_id),
        "shopping_item": [],
    }

    member_ids = _id_set(tables["household_member"])
    tables["target_profile"] = _rows(db, TargetProfile, TargetProfile.member_id.in_(member_ids)) if member_ids else []
    target_ids = _id_set(tables["target_profile"])
    tables["meal_allocation"] = _rows(db, MealAllocation, MealAllocation.target_profile_id.in_(target_ids)) if target_ids else []
    tables["restriction"] = _rows(db, Restriction, Restriction.member_id.in_(member_ids)) if member_ids else []

    recipe_ids = _id_set(tables["recipe"])
    tables["recipe_meal_type"] = _rows(db, RecipeMealType, RecipeMealType.recipe_id.in_(recipe_ids)) if recipe_ids else []
    tables["recipe_publisher_tag"] = _rows(db, RecipePublisherTag, RecipePublisherTag.recipe_id.in_(recipe_ids)) if recipe_ids else []
    tables["recipe_version"] = _rows(db, RecipeVersion, RecipeVersion.recipe_id.in_(recipe_ids)) if recipe_ids else []
    version_ids = _id_set(tables["recipe_version"])
    tables["recipe_ingredient"] = _rows(db, RecipeIngredient, RecipeIngredient.recipe_version_id.in_(version_ids)) if version_ids else []
    tables["recipe_method_snapshot"] = _rows(db, RecipeMethodSnapshot, RecipeMethodSnapshot.recipe_version_id.in_(version_ids)) if version_ids else []
    tables["nutrition_calculation"] = _rows(db, NutritionCalculation, NutritionCalculation.recipe_version_id.in_(version_ids)) if version_ids else []

    plan_ids = _id_set(tables["meal_plan"])
    tables["meal_batch"] = _rows(db, MealBatch, MealBatch.meal_plan_id.in_(plan_ids)) if plan_ids else []
    batch_ids = _id_set(tables["meal_batch"])
    tables["meal_occurrence"] = _rows(db, MealOccurrence, MealOccurrence.meal_plan_id.in_(plan_ids)) if plan_ids else []
    occurrence_ids = _id_set(tables["meal_occurrence"])
    tables["portion_allocation"] = _rows(db, PortionAllocation, PortionAllocation.meal_occurrence_id.in_(occurrence_ids)) if occurrence_ids else []
    tables["pantry_reservation"] = _rows(db, PantryReservation, PantryReservation.meal_batch_id.in_(batch_ids)) if batch_ids else []
    pantry_ids = _id_set(tables["pantry_lot"])
    tables["pantry_transaction"] = _rows(db, PantryTransaction, PantryTransaction.pantry_lot_id.in_(pantry_ids)) if pantry_ids else []

    shopping_ids = _id_set(tables["shopping_list"])
    tables["shopping_item"] = _rows(db, ShoppingItem, ShoppingItem.shopping_list_id.in_(shopping_ids)) if shopping_ids else []

    food_ids: set[str] = set()
    for table in (
        "recipe_ingredient",
        "household_food_unit_conversion",
        "saved_food",
        "pantry_lot",
        "shopping_item",
    ):
        food_ids.update(row["food_record_id"] for row in tables[table] if row.get("food_record_id"))
    source_owned = db.scalars(
        select(FoodRecord).where(
            or_(FoodRecord.owner_household_id == household_id, FoodRecord.id.in_(food_ids))
        )
    ).all()
    source_food_rows = {_row_data(row)["id"]: _row_data(row) for row in source_owned}
    pending_parent_ids = {
        row["source_food_record_id"]
        for row in source_food_rows.values()
        if row.get("source_food_record_id") and row["source_food_record_id"] not in source_food_rows
    }
    while pending_parent_ids:
        parents = db.scalars(select(FoodRecord).where(FoodRecord.id.in_(pending_parent_ids))).all()
        pending_parent_ids = set()
        for parent in parents:
            data = _row_data(parent)
            source_food_rows[data["id"]] = data
            if data.get("source_food_record_id") and data["source_food_record_id"] not in source_food_rows:
                pending_parent_ids.add(data["source_food_record_id"])
    tables["food_record"] = list(source_food_rows.values())
    food_ids.update(_id_set(tables["food_record"]))
    tables["food_nutrient"] = _rows(db, FoodNutrient, FoodNutrient.food_record_id.in_(food_ids)) if food_ids else []

    return SourceBundle(household=_row_data(household), tables=tables)


def _counts(bundle: SourceBundle) -> dict[str, dict[str, int]]:
    tables = bundle.tables
    return {
        "household": {
            "members": len(tables["household_member"]),
            "targets": len(tables["target_profile"]),
            "restrictions": len(tables["restriction"]),
        },
        "users": {"users": len(tables["app_user"])},
        "recipes": {
            "recipes": len(tables["recipe"]),
            "versions": len(tables["recipe_version"]),
            "ingredients": len(tables["recipe_ingredient"]),
            "methods": len(tables["recipe_method_snapshot"]),
        },
        "ingredients": {
            "food_records": len(tables["food_record"]),
            "saved_foods": len(tables["saved_food"]),
            "aliases": len(tables["food_alias"]),
            "unit_conversions": len(tables["household_food_unit_conversion"]),
        },
        "pantry": {"items": len(tables["pantry_lot"]), "movements": len(tables["pantry_transaction"])},
        "shopping": {"lists": len(tables["shopping_list"]), "items": len(tables["shopping_item"])},
        "plans": {
            "plans": len(tables["meal_plan"]),
            "batches": len(tables["meal_batch"]),
            "occurrences": len(tables["meal_occurrence"]),
        },
    }


def preview_archive(archive_value: str, source_household_id: str | None = None) -> dict[str, Any]:
    archive = resolve_archive(archive_value)
    verify_archive_checksums(archive)
    if not archive.database_dump:
        raise DomainError("BACKUP_INCOMPLETE", "This backup has no database.dump file.", 422)
    with _TemporaryDatabase(archive.path / "database.dump") as source_db:
        households = source_db.scalars(select(Household).order_by(Household.created_at, Household.id)).all()
        bundle = _load_source_bundle(source_db, source_household_id)
        selected_household = bundle.household
        selected_components = set(COMPONENTS)
        return {
            **archive.as_dict(),
            "households": [
                {"id": row.id, "name": row.name, "timezone": row.timezone}
                for row in households
            ],
            "selected_household": {
                "id": selected_household["id"],
                "name": selected_household["name"],
                "timezone": selected_household["timezone"],
            },
            "components": [
                {
                    "key": key,
                    **COMPONENT_INFO[key],
                    "counts": _counts(bundle)[key],
                }
                for key in COMPONENTS
            ],
            "dependencies": _restore_dependencies(selected_components, bundle.tables),
            "excluded": [
                {"key": "sessions", "label": "Active sessions", "reason": "Never imported; sign in with the target installation."},
                {"key": "integrations", "label": "API credentials", "reason": "Never imported; encrypted secrets stay on the target installation."},
                {"key": "pantry_reservations", "label": "Live pantry reservations", "reason": "Never imported; reservations belong to the target plan and inventory."},
            ],
        }


def _component_tables(components: set[str], tables: dict[str, list[dict[str, Any]]]) -> set[str]:
    include: set[str] = set()
    if "household" in components:
        include.update({"household_member", "household_meal_group_assignment", "target_profile", "meal_allocation", "restriction", "ingredient_name_override", "ingredient_name_equivalent"})
    if "users" in components:
        include.add("app_user")
    if "recipes" in components:
        include.update({"recipe", "recipe_meal_type", "recipe_publisher_tag", "recipe_version", "recipe_ingredient", "recipe_method_snapshot", "nutrition_calculation", "food_record", "food_nutrient"})
    if "ingredients" in components:
        include.update({"food_record", "food_nutrient", "household_food_unit_conversion", "saved_food", "food_alias", "ingredient_name_override", "ingredient_name_equivalent"})
    if "pantry" in components:
        include.update({"pantry_lot", "pantry_transaction", "food_record", "food_nutrient"})
    if "shopping" in components:
        include.update({"shopping_list", "shopping_item", "food_record", "food_nutrient"})
    if "plans" in components:
        include.update({
            "meal_plan", "meal_batch", "meal_occurrence", "portion_allocation",
            "recipe", "recipe_meal_type", "recipe_publisher_tag", "recipe_version", "recipe_ingredient", "recipe_method_snapshot", "nutrition_calculation",
            "household_member", "food_record", "food_nutrient",
        })
    return {table for table in include if tables.get(table)}


def _restore_dependencies(components: set[str], tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Describe dependencies and explicit clearing performed by a restore.

    A preview must make partial component selection understandable.  Required
    parents are included automatically by the selected component; nullable
    references are deliberately cleared when their source component is not
    selected.  Reservations are never included in a plan restore because they
    describe live target inventory rather than portable history.
    """

    dependencies: list[dict[str, Any]] = []

    def add(component: str, required_by: str, *, selected: bool, action: str) -> None:
        dependencies.append(
            {
                "component": component,
                "required_by": required_by,
                "selected": selected,
                "action": action,
            }
        )

    if "users" in components:
        add("household", "users", selected=True, action="target household is used")
        add(
            "household members",
            "users.member_id",
            selected="household" in components,
            action="kept when selected; otherwise nullable member links are cleared",
        )
    if "recipes" in components:
        add("household", "recipes", selected=True, action="target household is used")
        add("ingredients", "recipes", selected="ingredients" in components, action="food links are retained when selected; otherwise nullable links are cleared")
    if "ingredients" in components:
        add("household", "ingredients", selected=True, action="target household is used")
    if "pantry" in components:
        add("ingredients", "pantry", selected="ingredients" in components, action="food links are retained when selected; otherwise nullable links are cleared")
    if "shopping" in components:
        add("ingredients", "shopping", selected="ingredients" in components, action="food links are retained when selected; otherwise nullable links are cleared")
    if "plans" in components:
        add("recipes", "plans", selected=True, action="recipe history is included")
        add("household members", "plans", selected=True, action="member allocations are included")
        add("pantry reservations", "plans", selected=False, action="never imported; target inventory remains authoritative")
    return dependencies


def _as_target_value(value: Any) -> Any:
    return value


NUMERIC_COLUMNS = {
    "tolerance_percent", "calorie_target", "protein_target_g", "carbohydrate_target_g", "fat_target_g",
    "protein_min_g", "protein_max_g", "carbohydrate_min_g", "carbohydrate_max_g", "fat_min_g", "fat_max_g",
    "percentage", "yield_servings", "quantity", "quantity_grams", "nutrition_basis_amount_per_unit", "name_confidence", "basis_amount",
    "density_g_per_ml", "serving_amount", "amount", "servings", "cooked_weight_grams", "guest_servings",
    "exact_quantity", "purchase_quantity", "initial_quantity", "quantity_delta",
}


HISTORICAL_CLONE_TABLES = {
    "meal_plan",
    "meal_batch",
    "meal_occurrence",
    "portion_allocation",
    "shopping_list",
    "shopping_item",
}


def _historical_clone_id(target_household_id: str, table: str, source_id: str) -> str:
    """Return a stable target ID that can never reuse the live source row.

    Plans and shopping lists are imported as historical snapshots, including
    when the archive came from the target household itself.  A deterministic
    UUID keeps repeat restores idempotent while giving every aggregate and
    child a distinct identity from its live source object.
    """

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"slop-selective-restore:{target_household_id}:{table}:{source_id}",
        )
    )


def _prepare_historical_id_maps(
    tables: dict[str, list[dict[str, Any]]],
    include: set[str],
    maps: dict[str, dict[str, str]],
    target_household_id: str,
) -> None:
    """Reserve clone identities before remapping rows or embedded snapshots."""

    for table in HISTORICAL_CLONE_TABLES & include:
        for row in tables[table]:
            maps[table][row["id"]] = _historical_clone_id(
                target_household_id,
                table,
                row["id"],
            )


def _remap_embedded(value: Any, id_map: dict[str, dict[str, str]]) -> Any:
    """Remap UUID references inside JSON snapshots without changing prose."""

    if isinstance(value, dict):
        return {key: _remap_embedded(item, id_map) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap_embedded(item, id_map) for item in value]
    if isinstance(value, tuple):
        return tuple(_remap_embedded(item, id_map) for item in value)
    if isinstance(value, str):
        for mapping in id_map.values():
            if value in mapping:
                return mapping[value]
    return value


def _mapped_data(
    data: dict[str, Any],
    id_map: dict[str, dict[str, str]],
    model: Any | None = None,
) -> dict[str, Any]:
    foreign_keys = {
        "household_id": "household",
        "member_id": "household_member",
        "target_profile_id": "target_profile",
        "recipe_id": "recipe",
        "recipe_version_id": "recipe_version",
        "food_record_id": "food_record",
        "source_food_record_id": "food_record",
        "planner_recipe_id": "recipe",
        "meal_plan_id": "meal_plan",
        "batch_id": "meal_batch",
        "parent_batch_id": "meal_batch",
        "meal_occurrence_id": "meal_occurrence",
        "pantry_lot_id": "pantry_lot",
        "meal_batch_id": "meal_batch",
        "shopping_list_id": "shopping_list",
        "reviewed_by": "app_user",
        "created_by_user_id": "app_user",
        "reviewed_by_user_id": "app_user",
    }
    # Keep scalar foreign keys untouched until the mapping loop below.  The
    # recursive JSON remapper would otherwise map a scalar FK first, after
    # which the nullable-link guard could mistake the already-mapped target ID
    # for an omitted source component and clear it.
    result = {
        key: (
            _as_target_value(value)
            if key in foreign_keys
            else _remap_embedded(_as_target_value(value), id_map)
        )
        for key, value in data.items()
    }
    for foreign_key, map_name in foreign_keys.items():
        mapping = id_map.get(map_name, {})
        if foreign_key in result and result[foreign_key] in mapping:
            result[foreign_key] = mapping[result[foreign_key]]
        elif (
            model is not None
            and foreign_key in result
            and result[foreign_key] is not None
            and any(column.name == foreign_key and column.nullable for column in model.__table__.columns)
        ):
            # The source component was not selected.  Nullable links must not
            # leak source IDs into the target household or violate FK checks.
            result[foreign_key] = None
    return result


def _convert_model_values(model: Any, data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    for column in model.__table__.columns:
        value = result.get(column.name)
        if isinstance(value, str) and column.name in NUMERIC_COLUMNS:
            result[column.name] = Decimal(value)
        elif isinstance(value, str) and column.name in {"created_at", "updated_at", "expires_at", "accepted_at", "archived_at", "publisher_metadata_refreshed_at", "cooked_at", "calculated_at", "reviewed_at"}:
            result[column.name] = datetime.fromisoformat(value)
        elif isinstance(value, str) and column.name in {"start_date", "end_date", "planned_cook_date", "meal_date", "expires_on"}:
            result[column.name] = date.fromisoformat(value)
    return result


def _belongs_to_target(model: Any, existing: Any, data: dict[str, Any], maps: dict[str, dict[str, str]]) -> bool:
    """Reject an ID match that belongs to another household.

    A global UUID collision is possible when two installations are merged.  A
    matching primary key is only reusable when its household/owner or mapped
    parent proves that it is the same target record.
    """

    for field in ("household_id", "owner_household_id"):
        value = getattr(existing, field, None)
        expected = data.get(field)
        if value is not None and expected is not None and value != expected:
            return False
    identity_fields = {
        "household_member": ("name",),
        "app_user": ("username",),
        "recipe": ("title", "source_url"),
        "food_record": ("provider", "provider_record_id"),
        "saved_food": ("food_record_id",),
        "food_alias": ("phrase", "food_record_id"),
        "pantry_lot": ("display_name", "unit"),
        "shopping_list": ("name", "meal_plan_id"),
        "meal_plan": ("name", "start_date", "end_date"),
    }
    for field in identity_fields.get(model.__tablename__, ()):
        source_value = data.get(field)
        existing_value = getattr(existing, field, None)
        if source_value is not None and existing_value != source_value:
            return False
    table = model.__tablename__
    parent_fields = {
        "recipe_version": ("recipe_id", "recipe"),
        "recipe_ingredient": ("recipe_version_id", "recipe_version"),
        "recipe_method_snapshot": ("recipe_version_id", "recipe_version"),
        "recipe_meal_type": ("recipe_id", "recipe"),
        "recipe_publisher_tag": ("recipe_id", "recipe"),
        "nutrition_calculation": ("recipe_version_id", "recipe_version"),
        "food_nutrient": ("food_record_id", "food_record"),
        "meal_batch": ("meal_plan_id", "meal_plan"),
        "meal_occurrence": ("meal_plan_id", "meal_plan"),
        "portion_allocation": ("meal_occurrence_id", "meal_occurrence"),
        "pantry_transaction": ("pantry_lot_id", "pantry_lot"),
        "pantry_reservation": ("meal_batch_id", "meal_batch"),
        "shopping_item": ("shopping_list_id", "shopping_list"),
        "meal_allocation": ("target_profile_id", "target_profile"),
        "restriction": ("member_id", "household_member"),
        "household_meal_group_assignment": ("member_id", "household_member"),
    }
    parent = parent_fields.get(table)
    if parent:
        field, map_name = parent
        expected_parent = maps.get(map_name, {}).get(data.get(field))
        if expected_parent is not None and getattr(existing, field, None) != expected_parent:
            return False
    return True


def _find_existing(
    db: Session,
    model: Any,
    data: dict[str, Any],
    maps: dict[str, dict[str, str]],
) -> Any | None:
    existing = db.get(model, data["id"])
    if existing is not None and _belongs_to_target(model, existing, data, maps):
        maps[model.__tablename__][data["id"]] = existing.id
        return existing
    if existing is not None:
        # Do not accidentally reuse an ID from an unrelated household.  The
        # caller will allocate a new target ID before insertion.
        existing = None
    unique_filters: list[Any] = []
    table = model.__tablename__
    if table == "household_member":
        unique_filters = [model.household_id == data["household_id"], model.name == data["name"]]
    elif table == "app_user":
        unique_filters = [func.lower(model.username) == data["username"].lower()]
    elif table == "ingredient_name_equivalent":
        unique_filters = [model.us_name == data["us_name"], model.uk_name == data["uk_name"]]
    elif table == "ingredient_name_override":
        unique_filters = [model.household_id == data["household_id"], model.ingredient_key == data["ingredient_key"]]
    elif table == "household_meal_group_assignment":
        unique_filters = [
            model.household_id == data["household_id"],
            model.member_id == data["member_id"],
            model.meal_type == data["meal_type"],
        ]
    elif table == "food_record":
        unique_filters = [model.provider == data["provider"], model.provider_record_id == data["provider_record_id"]]
    elif table == "food_nutrient":
        unique_filters = [model.food_record_id == data["food_record_id"], model.code == data["code"]]
    elif table == "saved_food":
        unique_filters = [model.household_id == data["household_id"], model.food_record_id == data["food_record_id"]]
    elif table == "food_alias":
        unique_filters = [model.household_id == data["household_id"], model.phrase == data["phrase"]]
    elif table == "recipe_meal_type":
        unique_filters = [model.recipe_id == data["recipe_id"], model.meal_type == data["meal_type"]]
    elif table == "recipe_publisher_tag":
        unique_filters = [model.recipe_id == data["recipe_id"], model.kind == data["kind"], model.normalised_value == data["normalised_value"]]
    elif table == "recipe_version":
        unique_filters = [model.recipe_id == data["recipe_id"], model.version_number == data["version_number"]]
    elif table == "recipe_method_snapshot":
        unique_filters = [model.recipe_version_id == data["recipe_version_id"]]
    elif table == "meal_allocation":
        unique_filters = [model.target_profile_id == data["target_profile_id"], model.meal_type == data["meal_type"]]
    elif table == "target_profile":
        unique_filters = [model.member_id == data["member_id"]]
    elif table == "pantry_reservation":
        unique_filters = [model.pantry_lot_id == data["pantry_lot_id"], model.meal_batch_id == data["meal_batch_id"]]
    elif table == "portion_allocation":
        unique_filters = [model.meal_occurrence_id == data["meal_occurrence_id"], model.member_id == data["member_id"]]
    elif table == "meal_occurrence":
        unique_filters = [model.meal_plan_id == data["meal_plan_id"], model.meal_date == data["meal_date"], model.meal_type == data["meal_type"], model.meal_group_key == data.get("meal_group_key", "shared"), model.component_slot == data["component_slot"]]
    if unique_filters:
        existing = db.scalar(select(model).where(*unique_filters))
        if existing is not None and _belongs_to_target(model, existing, data, maps):
            maps[table][data["id"]] = existing.id
            return existing
    return None


def _insert_rows(db: Session, model: Any, rows: list[dict[str, Any]], maps: dict[str, dict[str, str]], household_id: str, source_household_id: str) -> int:
    table = model.__tablename__
    imported = 0
    if table == "food_record":
        rows = sorted(rows, key=lambda row: bool(row.get("source_food_record_id")))
    for source in rows:
        source_id = source["id"]
        data = _convert_model_values(model, source)
        if table in HISTORICAL_CLONE_TABLES:
            # The full restore reserves all historical IDs up front so JSON
            # snapshots can remap forward references too.  Keep direct helper
            # use safe by reserving this row lazily when necessary.
            maps[table].setdefault(
                source_id,
                _historical_clone_id(household_id, table, source_id),
            )
            data["id"] = maps[table][source_id]
        if "household_id" in data:
            data["household_id"] = household_id
        if "owner_household_id" in data and data["owner_household_id"] == source_household_id:
            data["owner_household_id"] = household_id
        if table == "household":
            maps[table][source_id] = household_id
            continue
        if table == "meal_batch":
            data["parent_batch_id"] = None
        if table == "meal_plan":
            # A restored plan is historical evidence, never an active plan
            # whose reservations can affect the current household.  The
            # source status is retained in diagnostics for auditability.
            source_status = data.get("status")
            data["status"] = PlanStatus.SUPERSEDED.value
            diagnostics = list(data.get("diagnostics") or [])
            diagnostics.append(
                {
                    "kind": "restore_history",
                    "source_status": source_status,
                    "message": "Restored as inactive history; pantry reservations were not imported.",
                }
            )
            data["diagnostics"] = diagnostics
            data["accepted_at"] = None
        if table == "shopping_list":
            data["active"] = False
            data["rebuild_recommended"] = True
        if table == "recipe_method_snapshot":
            data["created_by_user_id"] = None
            data["reviewed_by_user_id"] = None
        if table == "recipe":
            for field in ("source_url", "image_url"):
                try:
                    data[field] = canonicalize_url(data[field]) if data.get(field) else None
                except InvalidUrlError:
                    data[field] = None
        data = _mapped_data(data, maps, model)
        if table == "app_user":
            # Usernames are globally unique.  A source account whose name is
            # already owned by another household cannot be imported under the
            # same identity; skip it rather than linking or overwriting that
            # household's account.  Method snapshots clear author links and do
            # not depend on this optional row.
            conflicting_user = db.scalar(
                select(User).where(func.lower(User.username) == str(data.get("username", "")).lower())
            )
            if conflicting_user is not None and conflicting_user.household_id != household_id:
                continue
        existing = _find_existing(db, model, data, maps)
        if existing is not None:
            continue
        # A source UUID may already exist in another target household.  Never
        # attach the imported row to that record; allocate a fresh ID and keep
        # the source->target mapping for all child rows.
        # Historical aggregates already carry their deterministic clone ID;
        # using the source ID here would turn a same-household restore into a
        # random clone whenever the live source row is present, breaking
        # replay idempotence.  Other tables retain the source ID unless it
        # collides with an unrelated target row.
        target_id = data["id"]
        collision = db.get(model, target_id)
        if collision is not None:
            if table in HISTORICAL_CLONE_TABLES:
                # Keep collision recovery deterministic as well.  UUID5
                # collisions are extraordinarily unlikely, but a target may
                # already contain a user-created row with that exact ID.
                collision_attempt = 1
                target_id = _historical_clone_id(
                    household_id,
                    table,
                    f"{source_id}:collision:{collision_attempt}",
                )
                while db.get(model, target_id) is not None:
                    collision_attempt += 1
                    target_id = _historical_clone_id(
                        household_id,
                        table,
                        f"{source_id}:collision:{collision_attempt}",
                    )
            else:
                target_id = str(uuid.uuid4())
        data["id"] = target_id
        db.add(model(**data))
        db.flush()
        maps[table][source_id] = data["id"]
        imported += 1
    return imported


def restore_archive(
    archive_value: str,
    source_household_id: str | None,
    components: Iterable[str],
    target_db: Session,
    target_household_id: str,
) -> dict[str, Any]:
    requested = set(components)
    invalid = requested - set(COMPONENTS)
    if not requested or invalid:
        raise DomainError("INVALID_RESTORE_COMPONENTS", "Choose at least one valid restore component.", 422)
    if not RESTORE_LOCK.acquire(blocking=False):
        raise DomainError("RESTORE_IN_PROGRESS", "Another restore is already running.", 409)

    shared_lock = _backup_lock()
    shared_lock_entered = False
    try:
        try:
            shared_lock.__enter__()
            shared_lock_entered = True
        except Exception:
            raise
        archive = resolve_archive(archive_value)
        if not archive.database_dump:
            raise DomainError("BACKUP_INCOMPLETE", "This backup has no database.dump file.", 422)
        verify_archive_checksums(archive)
        with _TemporaryDatabase(archive.path / "database.dump") as source_db:
            bundle = _load_source_bundle(source_db, source_household_id)
            include = _component_tables(requested, bundle.tables)
            maps: dict[str, dict[str, str]] = defaultdict(dict)
            maps["household"][bundle.household["id"]] = target_household_id
            _prepare_historical_id_maps(
                bundle.tables,
                include,
                maps,
                target_household_id,
            )
            counts: dict[str, int] = defaultdict(int)

            ordered = (
                "ingredient_name_equivalent",
                "household_member",
                "household_meal_group_assignment",
                "target_profile",
                "meal_allocation",
                "restriction",
                "ingredient_name_override",
                "food_record",
                "food_nutrient",
                "household_food_unit_conversion",
                "recipe",
                "recipe_meal_type",
                "recipe_publisher_tag",
                "recipe_version",
                "recipe_ingredient",
                "nutrition_calculation",
                "app_user",
                "recipe_method_snapshot",
                "saved_food",
                "food_alias",
                "meal_plan",
                "meal_batch",
                "meal_occurrence",
                "portion_allocation",
                "pantry_lot",
                "pantry_transaction",
                "shopping_list",
                "shopping_item",
            )
            for table in ordered:
                if table not in include:
                    continue
                model = MODEL_BY_TABLE[table]
                counts[table] += _insert_rows(
                    target_db,
                    model,
                    bundle.tables[table],
                    maps,
                    target_household_id,
                    bundle.household["id"],
                )

            # Self-referential batch parents can be resolved after all batches
            # exist. Missing parent links are left null rather than inventing a
            # reference into the target database.
            if "meal_batch" in include:
                for source in bundle.tables["meal_batch"]:
                    target_id = maps["meal_batch"].get(source["id"])
                    parent_id = maps["meal_batch"].get(source.get("parent_batch_id"))
                    if target_id and parent_id:
                        batch = target_db.get(MealBatch, target_id)
                        if batch is not None and batch.parent_batch_id != parent_id:
                            batch.parent_batch_id = parent_id

            target_db.commit()
            return {
                "archive": archive.relative_path,
                "source_household": bundle.household["name"],
                "components": sorted(requested),
                "imported": {key: value for key, value in counts.items() if value},
                "dependencies": _restore_dependencies(requested, bundle.tables),
                "excluded": [
                    "Active sessions were not imported.",
                    "Encrypted integration credentials were not imported.",
                    "Live pantry reservations were not imported; restored plans are inactive history.",
                ],
            }
    except DomainError:
        target_db.rollback()
        raise
    except Exception as exc:
        target_db.rollback()
        trace_id = _trace_id()
        LOGGER.exception("Selective restore failed", extra={"trace_id": trace_id})
        raise DomainError(
            "RESTORE_FAILED",
            f"The selected data could not be imported (trace id {trace_id}).",
            422,
        ) from exc
    finally:
        try:
            if shared_lock_entered:
                shared_lock.__exit__(None, None, None)
        finally:
            RESTORE_LOCK.release()
