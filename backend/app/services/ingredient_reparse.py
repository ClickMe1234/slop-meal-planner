from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import MealBatch, Recipe, RecipeIngredient, RecipeVersion, ShoppingList
from .ingredient_names import ingredient_name_keys
from .ingredients import PARSER_VERSION, parse_ingredient


@dataclass(frozen=True, slots=True)
class ReparseResult:
    scanned: int
    changed: int
    flagged: int
    lists_marked: int


def reparse_stale_imported_ingredients(db: Session) -> ReparseResult:
    rows = db.scalars(
        select(RecipeIngredient)
        .join(RecipeVersion, RecipeVersion.id == RecipeIngredient.recipe_version_id)
        .join(Recipe, Recipe.id == RecipeVersion.recipe_id)
        .where(
            Recipe.source_type == "url",
            or_(
                RecipeIngredient.parser_version.is_(None),
                RecipeIngredient.parser_version != PARSER_VERSION,
            ),
        )
        .order_by(RecipeIngredient.recipe_version_id, RecipeIngredient.position)
    ).all()
    changed_version_ids: set[str] = set()
    changed = 0
    flagged = 0
    for row in rows:
        parsed = parse_ingredient(row.original_text)
        previous_name = row.parsed_food_phrase or row.food_phrase or row.original_text
        previous_keys = list(row.parser_name_keys or [])
        keys = list(
            dict.fromkeys(
                [
                    *ingredient_name_keys(db, parsed.food_phrase, previous_name),
                    *previous_keys,
                ]
            )
        )
        name_changed = " ".join(previous_name.casefold().split()) != " ".join(
            parsed.food_phrase.casefold().split()
        )
        amount_changed = parsed.quantity_calculated and (
            row.quantity != parsed.quantity
            or row.unit != parsed.unit
            or row.quantity_grams != parsed.quantity_grams
        )
        row.parsed_food_phrase = parsed.food_phrase
        row.parser_version = PARSER_VERSION
        row.name_confidence = (
            Decimal(str(round(parsed.name_confidence, 4)))
            if parsed.name_confidence is not None
            else None
        )
        row.parser_name_keys = keys
        if amount_changed:
            # Only deterministic arithmetic (for example 2 x 55 g or four
            # breast halves) is authoritative during automatic repair. This
            # avoids replacing ordinary quantities that a user may have
            # corrected while reviewing an imported recipe.
            row.quantity = parsed.quantity
            row.unit = parsed.unit
            row.quantity_grams = parsed.quantity_grams
        if not row.name_overridden:
            row.food_phrase = parsed.food_phrase
            row.preparation = parsed.preparation
            row.needs_review = parsed.needs_review
        if row.needs_review:
            flagged += 1
        if name_changed or amount_changed:
            changed += 1
            changed_version_ids.add(row.recipe_version_id)

    lists_marked = 0
    if changed_version_ids:
        affected_lists = db.scalars(
            select(ShoppingList)
            .join(MealBatch, MealBatch.meal_plan_id == ShoppingList.meal_plan_id)
            .where(
                ShoppingList.active.is_(True),
                MealBatch.recipe_version_id.in_(changed_version_ids),
            )
            .distinct()
        ).all()
        for shopping_list in affected_lists:
            if not shopping_list.rebuild_recommended:
                shopping_list.rebuild_recommended = True
                shopping_list.version += 1
                lists_marked += 1
    db.flush()
    return ReparseResult(len(rows), changed, flagged, lists_marked)
