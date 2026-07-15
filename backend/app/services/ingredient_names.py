from __future__ import annotations

import re

from nltk.stem.snowball import SnowballStemmer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IngredientNameOverride
from .regional_ingredients import canonical_ingredient_key, convert_ingredient_text


_STEMMER = SnowballStemmer("english")


def _stemmed_key(value: str) -> str:
    stemmed = re.sub(
        r"[a-z]+",
        lambda match: _STEMMER.stem(match.group(0)),
        value,
    )
    return f"stem:{stemmed}"


def ingredient_name_keys(db: Session, *names: str | None) -> list[str]:
    keys: list[str] = []
    for name in names:
        if not name:
            continue
        key = canonical_ingredient_key(db, name)
        if key and key not in keys:
            keys.append(key)
        stemmed_key = _stemmed_key(key)
        if key and stemmed_key not in keys:
            keys.append(stemmed_key)
    return keys


def household_name_overrides(db: Session, household_id: str) -> dict[str, str]:
    rows = db.scalars(
        select(IngredientNameOverride).where(
            IngredientNameOverride.household_id == household_id
        )
    ).all()
    return {row.ingredient_key: row.display_name for row in rows}


def preferred_ingredient_name(
    db: Session,
    household_id: str,
    keys: list[str],
    fallback: str,
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[str, bool]:
    values = overrides if overrides is not None else household_name_overrides(db, household_id)
    for key in keys:
        if key in values:
            return values[key], True
    return convert_ingredient_text(db, fallback, "uk") or fallback, False


def remember_ingredient_name(
    db: Session,
    household_id: str,
    keys: list[str],
    display_name: str,
) -> str:
    stored_name = (convert_ingredient_text(db, display_name.strip(), "uk") or display_name).strip()
    existing = {
        row.ingredient_key: row
        for row in db.scalars(
            select(IngredientNameOverride).where(
                IngredientNameOverride.household_id == household_id,
                IngredientNameOverride.ingredient_key.in_(keys),
            )
        ).all()
    } if keys else {}
    for key in keys:
        row = existing.get(key)
        if row is None:
            db.add(
                IngredientNameOverride(
                    household_id=household_id,
                    ingredient_key=key,
                    display_name=stored_name,
                )
            )
        elif row.display_name != stored_name:
            row.display_name = stored_name
            row.version += 1
    return stored_name
