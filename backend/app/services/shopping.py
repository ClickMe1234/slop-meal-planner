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
    for previous_list in previous_lists:
        previous_list.active = False
        previous_list.version += 1
    batches = db.scalars(
        select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
    ).all()
    requirements: dict[tuple[str | None, str, str], Decimal] = defaultdict(Decimal)
    review_actions: dict[str, dict] = {}
    for batch in batches:
        version = db.get(RecipeVersion, batch.recipe_version_id)
        if version is None or not version.yield_servings:
            raise DomainError("INVALID_BATCH", "A meal batch references an invalid recipe yield")
        scale = Decimal(batch.servings) / Decimal(version.yield_servings)
        for ingredient in version.ingredients:
            if not ingredient.included or ingredient.shopping_excluded:
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
            display = ingredient.food_phrase or ingredient.original_text
            requirements[(ingredient.food_record_id, display, unit)] += amount * scale

    if review_actions:
        count = len(review_actions)
        raise DomainError(
            "SHOPPING_REVIEW_REQUIRED",
            f"Confirm a shopping quantity for {count} recipe ingredient{'s' if count != 1 else ''}.",
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

    for (food_id, display, unit), exact in requirements.items():
        remaining = max(exact - plan_reserved[(food_id, unit)], Decimal("0"))
        if food_id:
            lots = db.scalars(
                select(PantryLot)
                .where(
                    PantryLot.household_id == household_id,
                    PantryLot.food_record_id == food_id,
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
                    and item.food_record_id == food_id
                    and item.display_name == display
                    and item.unit == unit
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
                )
            )
    db.flush()
    return shopping_list
