from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import DomainError, NotFoundError
from ..models import (
    FoodRecord,
    MealBatch,
    MealOccurrence,
    MealPlan,
    PantryLot,
    PantryReservation,
    RecipeVersion,
    ShoppingItem,
    ShoppingList,
)
from .pantry import balances
from .quantities import (
    canonical_quantity_unit,
    format_quantity,
    round_purchase_quantity,
    round_quantity,
)
from .ingredient_names import (
    household_name_overrides,
    ingredient_name_keys,
    preferred_ingredient_name,
)
from .measurement_conversion import (
    available_display_units,
    convert_quantity_to_unit,
    measurement_dimension,
    normalise_shopping_measurement,
    resolve_measurement_profile,
)
from .regional_ingredients import canonical_ingredient_key, convert_ingredient_text


def round_purchase(quantity: Decimal, unit: str) -> Decimal:
    return round_purchase_quantity(quantity, unit)


def build_shopping_list(
    db: Session, household_id: str, meal_plan_id: str, name: str
) -> ShoppingList:
    plan = db.get(MealPlan, meal_plan_id)
    if plan is None or plan.household_id != household_id:
        raise NotFoundError("Meal plan")
    previous_lists = db.scalars(
        select(ShoppingList)
        .where(ShoppingList.household_id == household_id, ShoppingList.active.is_(True))
        .order_by(ShoppingList.updated_at.desc())
    ).all()
    name_overrides = household_name_overrides(db, household_id)
    for previous_list in previous_lists:
        previous_list.active = False
        previous_list.version += 1
    batches = db.scalars(
        select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
    ).all()
    meal_dates_by_batch: dict[str, list[str]] = defaultdict(list)
    for occurrence in db.scalars(
        select(MealOccurrence)
        .where(MealOccurrence.meal_plan_id == plan.id)
        .order_by(MealOccurrence.meal_date)
    ).all():
        meal_dates_by_batch[occurrence.batch_id].append(occurrence.meal_date.isoformat())
    requirements: dict[tuple[str, str], dict[str, object]] = {}
    review_actions: dict[str, dict] = {}
    for batch in batches:
        if batch.cooked_at is not None:
            continue
        version = db.get(RecipeVersion, batch.recipe_version_id)
        if version is None or not version.yield_servings:
            raise DomainError("INVALID_BATCH", "A meal batch references an invalid recipe yield")
        scale = Decimal(batch.servings) / Decimal(version.yield_servings)
        for ingredient in version.ingredients:
            if not ingredient.included or ingredient.shopping_excluded:
                continue
            automatic_name = (
                ingredient.parsed_food_phrase
                or ingredient.food_phrase
                or ingredient.original_text
            )
            source_keys = list(
                dict.fromkeys(
                    [
                        *ingredient_name_keys(db, automatic_name),
                        *(ingredient.parser_name_keys or []),
                    ]
                )
            )
            base_name = (
                ingredient.food_phrase
                if ingredient.name_overridden and ingredient.food_phrase
                else automatic_name
            )
            display, remembered = preferred_ingredient_name(
                db,
                household_id,
                source_keys,
                base_name,
                overrides=name_overrides,
            )
            display_keys = ingredient_name_keys(db, display)
            source_keys = list(dict.fromkeys([*source_keys, *display_keys]))
            if ingredient.needs_review and not remembered:
                review_actions.setdefault(
                    ingredient.id,
                    {
                        "kind": "review_recipe",
                        "label": f"Confirm {ingredient.original_text}",
                        "href": (
                            f"/recipes/{version.recipe_id}/review?"
                            f"focusIngredient={ingredient.id}&focusField=name"
                        ),
                        "suggestion": (
                            "Confirm the ingredient name and shopping amount, or mark "
                            "Do not add to shopping list."
                        ),
                        "recipe_id": version.recipe_id,
                        "recipe_version_id": version.id,
                        "ingredient_id": ingredient.id,
                        "batch_id": batch.id,
                    },
                )
                continue
            food = db.get(FoodRecord, ingredient.food_record_id) if ingredient.food_record_id else None
            prepared_names = (
                [
                    f"{ingredient.preparation} {automatic_name}",
                    f"{automatic_name} {ingredient.preparation}",
                ]
                if ingredient.preparation
                else []
            )
            profile = resolve_measurement_profile(
                *prepared_names,
                automatic_name,
                base_name,
                display,
                food.name if food is not None else None,
            )
            density = (
                Decimal(food.density_g_per_ml)
                if food is not None and food.density_g_per_ml is not None
                else profile.density_g_per_ml if profile is not None else None
            )
            if ingredient.quantity is not None and ingredient.unit:
                source_amount = Decimal(ingredient.quantity)
                source_unit = canonical_quantity_unit(ingredient.unit)
            elif ingredient.quantity_grams is not None:
                source_amount, source_unit = Decimal(ingredient.quantity_grams), "g"
            elif ingredient.quantity is not None and ingredient.unit:
                source_amount = Decimal(ingredient.quantity)
                source_unit = canonical_quantity_unit(ingredient.unit)
            else:
                review_actions.setdefault(
                    ingredient.id,
                    {
                        "kind": "review_recipe",
                        "label": f"Fix {ingredient.original_text}",
                        "href": f"/recipes/{version.recipe_id}/review?focusIngredient={ingredient.id}",
                        "suggestion": (
                            "Enter a quantity and unit, or mark Do not add to shopping list."
                        ),
                        "recipe_id": version.recipe_id,
                        "recipe_version_id": version.id,
                        "ingredient_id": ingredient.id,
                        "batch_id": batch.id,
                    },
                )
                continue
            amount, unit = normalise_shopping_measurement(
                source_amount,
                source_unit,
                density,
            )
            source_display_unit = canonical_quantity_unit(source_unit)
            if source_display_unit == "l":
                source_display_unit = "ml"
            elif measurement_dimension(source_display_unit) == "mass":
                source_display_unit = "g"
            if source_display_unit not in available_display_units(unit, density):
                source_display_unit = available_display_units(unit, density)[0]
            grouping_key = ingredient.shopping_group_key or (
                f"measurement:{profile.canonical_name}"
                if profile is not None
                else next(
                    (value for value in display_keys if value.startswith("stem:")),
                    canonical_ingredient_key(db, display),
                )
            )
            if grouping_key not in source_keys:
                source_keys.append(grouping_key)
            key = (grouping_key, unit)
            requirement = requirements.setdefault(
                key,
                {
                    "food_id": ingredient.food_record_id,
                    "food_ids": {ingredient.food_record_id} if ingredient.food_record_id else set(),
                    "display": display,
                    "source_keys": set(source_keys),
                    "unit": unit,
                    "density": density,
                    "display_unit": source_display_unit,
                    "density_by_food": (
                        {ingredient.food_record_id: density}
                        if ingredient.food_record_id and density is not None
                        else {}
                    ),
                    "sources": [],
                    "exact": Decimal("0"),
                },
            )
            if requirement["food_id"] is None and ingredient.food_record_id:
                requirement["food_id"] = ingredient.food_record_id
            if ingredient.food_record_id:
                requirement["food_ids"].add(ingredient.food_record_id)
                if density is not None:
                    requirement["density_by_food"][ingredient.food_record_id] = density
            if requirement["density"] is None and density is not None:
                requirement["density"] = density
            requirement["source_keys"].update(source_keys)
            requirement["sources"].append(
                {
                    "recipe_id": version.recipe_id,
                    "recipe_title": version.title,
                    "recipe_version_id": version.id,
                    "recipe_ingredient_id": ingredient.id,
                    "shopping_group_key": ingredient.shopping_group_key,
                    "batch_id": batch.id,
                    "original_text": ingredient.original_text,
                    "preparation": ingredient.preparation,
                    "recipe_quantity": (
                        str(ingredient.quantity)
                        if ingredient.quantity is not None
                        else None
                    ),
                    "recipe_unit": ingredient.unit,
                    "plan_quantity": str(amount * scale),
                    "plan_unit": unit,
                    "meal_dates": meal_dates_by_batch.get(batch.id, []),
                    "cooked": batch.cooked_at is not None,
                }
            )
            requirement["exact"] = Decimal(requirement["exact"]) + amount * scale

    if review_actions:
        count = len(review_actions)
        raise DomainError(
            "SHOPPING_REVIEW_REQUIRED",
            f"Review {count} recipe ingredient{'s' if count != 1 else ''} before building the shopping list.",
            actions=list(review_actions.values()),
        )

    # Stock reserved for this accepted plan is already spoken for by these
    # batches. Count it as pantry usage instead of treating it as unavailable
    # and buying the full requirement again.
    plan_reserved: dict[tuple[str | None, str], Decimal] = defaultdict(Decimal)
    batch_ids = [batch.id for batch in batches]
    if batch_ids:
        reservations = db.scalars(
            select(PantryReservation).where(PantryReservation.meal_batch_id.in_(batch_ids))
        ).all()
        for reservation in reservations:
            lot = db.get(PantryLot, reservation.pantry_lot_id)
            if lot is not None:
                reservation_unit = canonical_quantity_unit(reservation.unit)
                plan_reserved[(lot.food_record_id, reservation_unit)] += Decimal(
                    reservation.quantity
                )

    shopping_list = ShoppingList(
        household_id=household_id, meal_plan_id=plan.id, name=name, active=True
    )
    db.add(shopping_list)
    db.flush()

    for requirement in requirements.values():
        food_id = requirement["food_id"]
        food_ids = requirement["food_ids"]
        display = convert_ingredient_text(db, str(requirement["display"]), "uk") or str(requirement["display"])
        unit = canonical_quantity_unit(str(requirement["unit"]))
        source_keys = set(requirement["source_keys"])
        exact = Decimal(requirement["exact"])
        default_density = requirement["density"]
        density_by_food = requirement["density_by_food"]
        reserved = Decimal("0")
        for (candidate_id, reservation_unit), quantity in plan_reserved.items():
            if candidate_id not in food_ids:
                continue
            converted = convert_quantity_to_unit(
                quantity,
                reservation_unit,
                unit,
                density_by_food.get(candidate_id, default_density),
            )
            if converted is not None:
                reserved += converted
        remaining = max(exact - reserved, Decimal("0"))
        pantry_unit_conflicts: list[dict[str, object]] = []
        lots = db.scalars(
            select(PantryLot)
            .where(PantryLot.household_id == household_id)
            .order_by(PantryLot.expires_on.asc().nullslast())
        ).all()
        for lot in lots:
            matches_food = bool(
                food_ids
                and lot.food_record_id
                and lot.food_record_id in food_ids
            )
            matches_confirmed_name = bool(
                source_keys.intersection(lot.shopping_name_keys or [])
            )
            if not matches_food and not matches_confirmed_name:
                continue
            _, _, usable = balances(db, lot)
            converted = convert_quantity_to_unit(
                usable,
                lot.unit,
                unit,
                density_by_food.get(lot.food_record_id, default_density),
            )
            if converted is None:
                if usable > 0:
                    lot_unit = canonical_quantity_unit(lot.unit)
                    pantry_unit_conflicts.append(
                        {
                            "pantry_lot_id": lot.id,
                            "display_name": lot.display_name,
                            "usable_quantity": str(usable),
                            "unit": lot_unit,
                            "usable_quantity_display": format_quantity(
                                usable, lot_unit
                            ),
                        }
                    )
                continue
            remaining -= min(max(converted, Decimal("0")), remaining)
            if remaining <= 0:
                break
        if remaining > 0:
            display_unit = str(requirement["display_unit"])
            db.add(
                ShoppingItem(
                    shopping_list_id=shopping_list.id,
                    food_record_id=food_id,
                    display_name=display,
                    exact_quantity=round_quantity(remaining, unit),
                    purchase_quantity=round_purchase(remaining, unit),
                    unit=unit,
                    density_g_per_ml=default_density,
                    display_unit=display_unit,
                    category="Other",
                    checked=False,
                    manual=False,
                    source_name_keys=sorted(source_keys),
                    source_ingredients=list(requirement["sources"]),
                    pantry_unit_conflicts=pantry_unit_conflicts,
                )
            )
    db.flush()
    return shopping_list
