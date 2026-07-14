from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IngredientLocale, IngredientNameEquivalent


@dataclass(frozen=True, slots=True)
class NameGroup:
    names: frozenset[str]
    preferred_uk: str
    preferred_us: str


def _groups(db: Session) -> tuple[NameGroup, ...]:
    cached = db.info.get("ingredient_name_groups")
    if cached is not None:
        return cached
    rows = db.scalars(
        select(IngredientNameEquivalent).order_by(
            IngredientNameEquivalent.priority,
            IngredientNameEquivalent.id,
        )
    ).all()
    parent: dict[str, str] = {}

    def find(name: str) -> str:
        parent.setdefault(name, name)
        if parent[name] != name:
            parent[name] = find(parent[name])
        return parent[name]

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for row in rows:
        union(row.uk_name.casefold(), row.us_name.casefold())

    names_by_root: dict[str, set[str]] = defaultdict(set)
    for name in parent:
        names_by_root[find(name)].add(name)

    result: list[NameGroup] = []
    for names in names_by_root.values():
        matching = [
            row for row in rows
            if row.uk_name.casefold() in names or row.us_name.casefold() in names
        ]
        preferred = min(matching, key=lambda row: (row.priority, row.id))
        result.append(
            NameGroup(
                frozenset(names),
                preferred.uk_name,
                preferred.us_name,
            )
        )
    groups = tuple(result)
    db.info["ingredient_name_groups"] = groups
    return groups


def equivalent_terms(db: Session, text: str) -> tuple[str, ...]:
    cleaned = " ".join(text.casefold().split())
    terms = {cleaned}
    for group in _groups(db):
        for name in group.names:
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", cleaned):
                terms.update(group.names)
    return tuple(sorted(terms, key=lambda value: (-len(value), value)))


def convert_ingredient_text(db: Session, text: str | None, locale: str | IngredientLocale) -> str | None:
    if not text:
        return text
    target = locale.value if isinstance(locale, IngredientLocale) else locale
    converted = text
    replacements: list[tuple[str, str]] = []
    for group in _groups(db):
        replacement = group.preferred_uk if target == IngredientLocale.UK.value else group.preferred_us
        replacements.extend((name, replacement) for name in group.names if name != replacement.casefold())
    for name, replacement in sorted(replacements, key=lambda item: -len(item[0])):
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE)

        def preserve_case(match: re.Match[str]) -> str:
            value = match.group(0)
            if value.isupper():
                return replacement.upper()
            if value[:1].isupper():
                return replacement[:1].upper() + replacement[1:]
            return replacement

        converted = pattern.sub(preserve_case, converted)
    return converted


def query_for_locale(db: Session, query: str, locale: str | IngredientLocale) -> str:
    return convert_ingredient_text(db, query, locale) or query


def canonical_ingredient_key(db: Session, text: str) -> str:
    canonical = convert_ingredient_text(db, text, IngredientLocale.UK) or text
    return " ".join(canonical.casefold().split())
