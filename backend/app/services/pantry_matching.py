from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FoodRecord, PantryLot, Recipe, RecipeVersion
from .regional_ingredients import canonical_ingredient_key, convert_ingredient_text


def pantry_name_similarity(db: Session, pantry_name: str, ingredient_name: str) -> float:
    left = canonical_ingredient_key(db, pantry_name)
    right = canonical_ingredient_key(db, ingredient_name)
    if not left or not right:
        return 0
    if left == right:
        return 1
    left_tokens = set(re.findall(r"[a-z0-9]+", left))
    right_tokens = set(re.findall(r"[a-z0-9]+", right))
    if not left_tokens or not right_tokens:
        return 0
    if left_tokens.issubset(right_tokens) or right_tokens.issubset(left_tokens):
        shorter = min(len(left_tokens), len(right_tokens))
        longer = max(len(left_tokens), len(right_tokens))
        return 0.84 + (0.12 * shorter / longer)
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(overlap * 0.82, sequence * 0.68)


def pantry_match_candidates(
    db: Session,
    household_id: str,
    lot: PantryLot,
    ingredient_locale: str = "uk",
    *,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Suggest food identities from the household's current saved recipes."""

    recipes = db.scalars(
        select(Recipe).where(
            Recipe.household_id == household_id,
            Recipe.archived_at.is_(None),
        )
    ).all()
    by_food: dict[str, dict[str, object]] = {}
    for recipe in recipes:
        version = db.scalar(
            select(RecipeVersion)
            .where(RecipeVersion.recipe_id == recipe.id)
            .order_by(RecipeVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            continue
        for ingredient in version.ingredients:
            if not ingredient.included or not ingredient.food_record_id:
                continue
            food = db.get(FoodRecord, ingredient.food_record_id)
            if food is None:
                continue
            names = [
                ingredient.parsed_food_phrase,
                ingredient.food_phrase,
                food.name,
            ]
            scored_names = [
                (pantry_name_similarity(db, lot.display_name, name), name)
                for name in names
                if name
            ]
            if not scored_names:
                continue
            score, matched_name = max(scored_names, key=lambda value: value[0])
            if score < 0.45:
                continue
            current = by_food.get(food.id)
            if current is None or score > float(current["confidence"]):
                by_food[food.id] = {
                    "food_record_id": food.id,
                    "display_name": convert_ingredient_text(
                        db, matched_name, ingredient_locale
                    ) or matched_name,
                    "confidence": round(score, 3),
                }
    return sorted(
        by_food.values(),
        key=lambda item: (-float(item["confidence"]), str(item["display_name"]).casefold()),
    )[:limit]
