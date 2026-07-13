from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import DomainError, NotFoundError
from ..models import (
    FoodNutrient,
    FoodRecord,
    NutritionCalculation,
    Recipe,
    RecipeEligibility,
    RecipeVersion,
)

REQUIRED_NUTRIENTS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g")


def _as_json(values: dict[str, Decimal]) -> dict[str, float]:
    return {key: round(float(value), 3) for key, value in values.items()}


def _publisher_values(version: RecipeVersion) -> dict[str, Decimal] | None:
    nutrition = version.publisher_nutrition
    if not isinstance(nutrition, dict):
        return None
    basis = str(nutrition.get("basis") or "").casefold().replace(" ", "")
    if "100g" in basis or "100ml" in basis:
        return None
    values: dict[str, Decimal] = {}
    for code in REQUIRED_NUTRIENTS:
        value = nutrition.get(code)
        if value is None:
            return None
        try:
            values[code] = Decimal(str(value))
        except Exception:
            return None
    return values


def _volume_in_ml(quantity: Decimal | None, unit: str | None) -> Decimal | None:
    if quantity is None or not unit:
        return None
    factors = {
        "ml": Decimal("1"), "millilitre": Decimal("1"), "millilitres": Decimal("1"),
        "l": Decimal("1000"), "litre": Decimal("1000"), "litres": Decimal("1000"),
        "tsp": Decimal("5"), "teaspoon": Decimal("5"), "teaspoons": Decimal("5"),
        "tbsp": Decimal("15"), "tablespoon": Decimal("15"), "tablespoons": Decimal("15"),
        "cup": Decimal("240"), "cups": Decimal("240"),
    }
    factor = factors.get(unit.casefold())
    return Decimal(quantity) * factor if factor is not None else None


def calculate_recipe(db: Session, recipe_version_id: str) -> NutritionCalculation:
    version = db.get(RecipeVersion, recipe_version_id)
    if version is None:
        raise NotFoundError("Recipe version")
    if not version.yield_servings or version.yield_servings <= 0:
        raise DomainError("MISSING_YIELD", "Confirm a positive serving yield before calculating")

    recipe = db.get(Recipe, version.recipe_id)
    publisher_values = _publisher_values(version)
    if publisher_values is not None:
        totals = {code: value * Decimal(version.yield_servings) for code, value in publisher_values.items()}
        source = recipe.publisher or recipe.source_url if recipe is not None else "recipe publisher"
        calculation = NutritionCalculation(
            recipe_version_id=version.id,
            status="publisher",
            total_values=_as_json(totals),
            per_serving_values=_as_json(publisher_values),
            contributions=[],
            assumptions=["Publisher-reported per-serving nutrition was used; ingredient calculation remains the fallback."],
            dataset_snapshot={"publisher": source or "recipe publisher"},
        )
        db.add(calculation)
        if recipe is not None:
            recipe.eligibility = RecipeEligibility.PLANNER_READY.value
            recipe.version += 1
        db.flush()
        return calculation

    if not version.ingredients:
        raise DomainError("MISSING_INGREDIENTS", "The recipe has no ingredients")

    totals = {code: Decimal("0") for code in REQUIRED_NUTRIENTS}
    contributions: list[dict] = []
    dataset_snapshot: dict[str, str] = {}
    assumptions: list[str] = []
    blocking: list[str] = []

    for ingredient in version.ingredients:
        if not ingredient.included:
            continue
        if ingredient.needs_review:
            blocking.append(f"Review ingredient: {ingredient.original_text}")
            continue
        if not ingredient.food_record_id:
            blocking.append(f"Choose a food match: {ingredient.original_text}")
            continue
        food = db.get(FoodRecord, ingredient.food_record_id)
        if food is None:
            blocking.append(f"Food match no longer exists: {ingredient.original_text}")
            continue
        if food.basis_unit == "g":
            amount = ingredient.quantity_grams
            if amount is None and ingredient.unit in ("g", "gram", "grams"):
                amount = ingredient.quantity
        elif food.basis_unit == "ml":
            amount = _volume_in_ml(ingredient.quantity, ingredient.unit)
        else:
            amount = None
        if amount is None:
            blocking.append(f"Convert ingredient to {food.basis_unit}: {ingredient.original_text}")
            continue

        nutrient_rows = db.scalars(
            select(FoodNutrient).where(FoodNutrient.food_record_id == food.id)
        ).all()
        nutrient_map = {row.code: row for row in nutrient_rows}
        missing = [
            code
            for code in REQUIRED_NUTRIENTS
            if code not in nutrient_map or nutrient_map[code].amount is None
        ]
        if missing:
            blocking.append(f"Missing {', '.join(missing)} for {food.name}")
            continue
        factor = Decimal(amount) / Decimal(food.basis_amount)
        item_values = {
            code: Decimal(nutrient_map[code].amount) * factor for code in REQUIRED_NUTRIENTS
        }
        for code, value in item_values.items():
            totals[code] += value
        dataset_snapshot[food.provider] = food.dataset_version
        contributions.append(
            {
                "ingredient_id": ingredient.id,
                "original_text": ingredient.original_text,
                "food_record_id": food.id,
                "food_name": food.name,
                "amount": float(amount),
                "unit": food.basis_unit,
                "values": _as_json(item_values),
            }
        )

    if blocking:
        raise DomainError("NUTRITION_REVIEW_REQUIRED", "; ".join(blocking))

    per_serving = {code: value / Decimal(version.yield_servings) for code, value in totals.items()}
    calculation = NutritionCalculation(
        recipe_version_id=version.id,
        status="complete",
        total_values=_as_json(totals),
        per_serving_values=_as_json(per_serving),
        contributions=contributions,
        assumptions=assumptions,
        dataset_snapshot=dataset_snapshot,
    )
    db.add(calculation)
    if recipe is not None:
        recipe.eligibility = RecipeEligibility.PLANNER_READY.value
        recipe.version += 1
    db.flush()
    return calculation


def latest_calculation(db: Session, recipe_version_id: str) -> NutritionCalculation | None:
    return db.scalar(
        select(NutritionCalculation)
        .where(NutritionCalculation.recipe_version_id == recipe_version_id)
        .order_by(NutritionCalculation.calculated_at.desc())
    )
