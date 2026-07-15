from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_CEILING

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import DomainError, NotFoundError
from ..models import (
    MealBatch,
    MealPlan,
    PantryLot,
    PantryReservation,
    RecipeVersion,
    ShoppingItem,
    ShoppingList,
)
from .pantry import balances
from .ingredient_names import (
    household_name_overrides,
    ingredient_name_keys,
    preferred_ingredient_name,
)
from .regional_ingredients import canonical_ingredient_key, convert_ingredient_text


COUNT_UNITS = {"count", "each", "item", "egg", "eggs"}


def round_purchase(quantity: Decimal, unit: str) -> Decimal:
    if unit.lower() in COUNT_UNITS:
        return quantity.to_integral_value(rounding=ROUND_CEILING)
    return quantity


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
    previous = previous_lists[0] if previous_lists else None
    previous_items = []
    if previous is not None:
        previous_items = db.scalars(
            select(ShoppingItem).where(ShoppingItem.shopping_list_id == previous.id)
        ).all()
    name_overrides = household_name_overrides(db, household_id)
    for previous_list in previous_lists:
        previous_list.active = False
        previous_list.version += 1
    batches = db.scalars(
        select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
    ).all()
    requirements: dict[tuple[str, str], dict[str, object]] = {}
    review_actions: dict[str, dict] = {}
    for batch in batches:
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
            if ingredient.quantity_grams is not None:
                amount, unit = Decimal(ingredient.quantity_grams), "g"
            elif ingredient.quantity is not None and ingredient.unit:
                amount, unit = Decimal(ingredient.quantity), ingredient.unit
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
            grouping_key = next(
                (value for value in source_keys if value.startswith("stem:")),
                canonical_ingredient_key(db, display),
            )
            key = (grouping_key, unit.casefold())
            requirement = requirements.setdefault(
                key,
                {
                    "food_id": ingredient.food_record_id,
                    "food_ids": {ingredient.food_record_id} if ingredient.food_record_id else set(),
                    "display": display,
                    "source_keys": set(source_keys),
                    "unit": unit,
                    "exact": Decimal("0"),
                },
            )
            if requirement["food_id"] is None and ingredient.food_record_id:
                requirement["food_id"] = ingredient.food_record_id
            if ingredient.food_record_id:
                requirement["food_ids"].add(ingredient.food_record_id)
            requirement["source_keys"].update(source_keys)
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
                plan_reserved[(lot.food_record_id, reservation.unit)] += Decimal(reservation.quantity)

    shopping_list = ShoppingList(
        household_id=household_id, meal_plan_id=plan.id, name=name, active=True
    )
    db.add(shopping_list)
    db.flush()

    for requirement in requirements.values():
        food_id = requirement["food_id"]
        food_ids = requirement["food_ids"]
        display = convert_ingredient_text(db, str(requirement["display"]), "uk") or str(requirement["display"])
        unit = str(requirement["unit"])
        source_keys = set(requirement["source_keys"])
        exact = Decimal(requirement["exact"])
        reserved = sum(
            (plan_reserved[(candidate_id, unit)] for candidate_id in food_ids),
            Decimal("0"),
        )
        remaining = max(exact - reserved, Decimal("0"))
        if food_ids:
            lots = db.scalars(
                select(PantryLot)
                .where(
                    PantryLot.household_id == household_id,
                    PantryLot.food_record_id.in_(food_ids),
                    PantryLot.unit == unit,
                )
                .order_by(PantryLot.expires_on.asc().nullslast())
            ).all()
            for lot in lots:
                _, _, usable = balances(db, lot)
                remaining -= min(max(usable, Decimal("0")), remaining)
                if remaining <= 0:
                    break
        if remaining > 0:
            prior = next(
                (
                    item
                    for item in previous_items
                    if not item.manual
                    and item.unit == unit
                    and (
                        (
                            food_id is not None
                            and item.food_record_id == food_id
                        )
                        or bool(
                            source_keys.intersection(
                                item.source_name_keys
                                or [canonical_ingredient_key(db, item.display_name)]
                            )
                        )
                    )
                ),
                None,
            )
            db.add(
                ShoppingItem(
                    shopping_list_id=shopping_list.id,
                    food_record_id=food_id,
                    display_name=display,
                    exact_quantity=remaining,
                    purchase_quantity=round_purchase(remaining, unit),
                    unit=unit,
                    category="Other",
                    checked=prior.checked if prior is not None else False,
                    manual=False,
                    source_name_keys=sorted(source_keys),
                )
            )
    for item in previous_items:
        if item.manual:
            db.add(
                ShoppingItem(
                    shopping_list_id=shopping_list.id,
                    food_record_id=item.food_record_id,
                    display_name=item.display_name,
                    exact_quantity=item.exact_quantity,
                    purchase_quantity=item.purchase_quantity,
                    unit=item.unit,
                    category=item.category,
                    checked=item.checked,
                    manual=True,
                    source_name_keys=list(item.source_name_keys or []),
                )
            )
    db.flush()
    return shopping_list
