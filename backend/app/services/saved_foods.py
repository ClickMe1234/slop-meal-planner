from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..data_import.models import DatasetProvenance, FoodDataBatch, NormalizedFood
from ..data_import.persistence import persist_food_batch
from ..errors import ConflictError, DomainError, NotFoundError
from ..models import (
    FoodNutrient,
    FoodRecord,
    Recipe,
    RecipeEligibility,
    RecipeIngredient,
    RecipeMealType,
    RecipeVersion,
    SavedFood,
)
from ..schemas import FoodNutrientIn, SavedFoodOut
from .nutrition import REQUIRED_NUTRIENTS, calculate_recipe


def accessible_food_record(db: Session, food_record_id: str, household_id: str) -> FoodRecord:
    record = db.get(FoodRecord, food_record_id)
    if record is None or record.owner_household_id not in {None, household_id}:
        raise NotFoundError("Food record")
    return record


def nutrient_values(record: FoodRecord) -> dict[str, Decimal | None]:
    values = {item.code: item.amount for item in record.nutrients}
    return {code: values.get(code) for code in REQUIRED_NUTRIENTS}


def complete_nutrition(record: FoodRecord) -> bool:
    values = nutrient_values(record)
    return all(values.get(code) is not None for code in REQUIRED_NUTRIENTS)


def _metadata_decimal(metadata: dict, key: str) -> Decimal | None:
    value = metadata.get(key)
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def saved_food_out(db: Session, saved: SavedFood) -> SavedFoodOut:
    record = accessible_food_record(db, saved.food_record_id, saved.household_id)
    metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
    meal_types: list[str] = []
    if saved.planner_recipe_id:
        meal_types = list(
            db.scalars(
                select(RecipeMealType.meal_type)
                .where(RecipeMealType.recipe_id == saved.planner_recipe_id)
                .order_by(RecipeMealType.meal_type)
            ).all()
        )
    values = nutrient_values(record)
    warnings: list[str] = []
    if any(value is None for value in values.values()):
        warnings.append("Complete calories and macros before using this food for planning.")
    if metadata.get("basis_inferred"):
        warnings.append("Confirm whether the label values are per 100g or per 100ml.")
    return SavedFoodOut(
        id=saved.id,
        display_name=saved.display_name,
        food_record_id=record.id,
        provider=record.provider,
        provider_record_id=record.provider_record_id,
        barcode=(record.provider_record_id if record.provider == "open_food_facts" else None),
        brand=str(metadata.get("brands") or "") or None,
        dataset_version=record.dataset_version,
        basis_amount=record.basis_amount,
        basis_unit=record.basis_unit,
        nutrients=values,
        serving_amount=saved.serving_amount,
        serving_unit=saved.serving_unit,
        planner_enabled=saved.planner_enabled,
        planner_recipe_id=saved.planner_recipe_id,
        meal_types=meal_types,
        package_amount=_metadata_decimal(metadata, "package_amount"),
        package_unit=metadata.get("package_unit"),
        source_url=metadata.get("source_url"),
        attribution=metadata.get("attribution"),
        warnings=warnings,
        version=saved.version,
    )


def persist_open_food_facts(db: Session, food: NormalizedFood) -> FoodRecord:
    persist_food_batch(
        db,
        FoodDataBatch(
            provenance=DatasetProvenance(
                provider=food.provider,
                dataset_version=food.dataset_version,
                source_uri=str(food.metadata.get("source_url") or "https://world.openfoodfacts.org"),
                license_name="Open Food Facts database (ODbL)",
            ),
            foods=(food,),
        ),
    )
    record = db.scalar(
        select(FoodRecord).where(
            FoodRecord.provider == food.provider,
            FoodRecord.provider_record_id == food.provider_record_id,
        )
    )
    if record is None:
        raise DomainError("FOOD_SAVE_FAILED", "The selected food could not be stored", 500)
    return record


def create_manual_record(
    db: Session,
    household_id: str,
    *,
    name: str,
    basis_amount: Decimal,
    basis_unit: str,
    nutrients: list[FoodNutrientIn],
    source_record: FoodRecord | None = None,
) -> FoodRecord:
    values = {item.code: item for item in nutrients}
    missing = [code for code in REQUIRED_NUTRIENTS if code not in values]
    if missing:
        raise DomainError(
            "INCOMPLETE_NUTRITION",
            f"Enter {', '.join(missing)} before saving this food",
        )
    record = FoodRecord(
        owner_household_id=household_id,
        source_food_record_id=(
            (source_record.source_food_record_id or source_record.id)
            if source_record
            else None
        ),
        provider="user",
        provider_record_id=str(uuid.uuid4()),
        dataset_version="Household manual entry",
        name=name.strip(),
        basis_amount=basis_amount,
        basis_unit=basis_unit,
        metadata_json={
            "attribution": "Household entry",
            "source_url": (
                (source_record.metadata_json or {}).get("source_url") if source_record else None
            ),
        },
    )
    db.add(record)
    db.flush()
    for item in values.values():
        db.add(FoodNutrient(food_record_id=record.id, **item.model_dump()))
    db.flush()
    return record


def _latest_recipe_version(db: Session, recipe_id: str) -> RecipeVersion | None:
    return db.scalar(
        select(RecipeVersion)
        .where(RecipeVersion.recipe_id == recipe_id)
        .order_by(RecipeVersion.version_number.desc())
    )


def sync_planner_food(
    db: Session,
    saved: SavedFood,
    *,
    meal_types: list[str],
) -> None:
    recipe = db.get(Recipe, saved.planner_recipe_id) if saved.planner_recipe_id else None
    if not saved.planner_enabled:
        if recipe is not None:
            recipe.archived_at = datetime.now(timezone.utc)
            recipe.eligibility = RecipeEligibility.ARCHIVED.value
            recipe.version += 1
        return
    if saved.serving_amount is None or saved.serving_unit is None or not meal_types:
        raise DomainError(
            "PLANNER_SERVING_REQUIRED",
            "Confirm a serving and at least one meal type before enabling planning",
        )
    record = accessible_food_record(db, saved.food_record_id, saved.household_id)
    if not complete_nutrition(record):
        raise DomainError(
            "INCOMPLETE_NUTRITION",
            "Complete calories and macros before enabling planning",
        )
    if record.basis_unit != saved.serving_unit:
        raise DomainError(
            "INCOMPATIBLE_SERVING_UNIT",
            f"Use a serving measured in {record.basis_unit}",
        )
    if recipe is None:
        recipe = Recipe(
            household_id=saved.household_id,
            title=saved.display_name,
            source_type="food",
            eligibility=RecipeEligibility.DRAFT.value,
        )
        db.add(recipe)
        db.flush()
        saved.planner_recipe_id = recipe.id
        version_number = 1
    else:
        latest = _latest_recipe_version(db, recipe.id)
        version_number = (latest.version_number if latest else 0) + 1
        recipe.title = saved.display_name
        recipe.archived_at = None
        recipe.eligibility = RecipeEligibility.DRAFT.value
        recipe.version += 1
    db.execute(delete(RecipeMealType).where(RecipeMealType.recipe_id == recipe.id))
    for meal_type in sorted(set(meal_types)):
        db.add(RecipeMealType(recipe_id=recipe.id, meal_type=meal_type))
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=version_number,
        title=saved.display_name,
        yield_servings=Decimal("1"),
    )
    db.add(version)
    db.flush()
    amount = Decimal(saved.serving_amount)
    db.add(
        RecipeIngredient(
            recipe_version_id=version.id,
            position=0,
            original_text=f"{amount:g} {saved.serving_unit} {saved.display_name}",
            quantity=amount,
            unit=saved.serving_unit,
            quantity_grams=amount if saved.serving_unit == "g" else None,
            food_phrase=saved.display_name,
            parsed_food_phrase=saved.display_name,
            included=True,
            optional=False,
            needs_review=False,
            shopping_excluded=False,
            food_record_id=record.id,
        )
    )
    db.flush()
    calculate_recipe(db, version.id)


def get_saved_food(db: Session, saved_food_id: str, household_id: str) -> SavedFood:
    saved = db.get(SavedFood, saved_food_id)
    if saved is None or saved.household_id != household_id or saved.archived_at is not None:
        raise NotFoundError("Saved food")
    return saved


def assert_version(saved: SavedFood, expected_version: int) -> None:
    if saved.version != expected_version:
        raise ConflictError("This ingredient changed while you were editing it. Reload and try again.")
