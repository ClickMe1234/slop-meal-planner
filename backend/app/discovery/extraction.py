from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any

from .html import RecipeHtmlParser
from .models import ExtractedRecipe, PublisherNutritionPreview
from .urls import canonicalize_url

# Recipe quantities are non-negative. Treating the separator in ``4-6`` as a
# minus sign previously made a serving range parse as 4 and -6.
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _types(value: object) -> set[str]:
    if isinstance(value, str):
        return {value.lower()}
    if isinstance(value, list):
        return {str(item).lower() for item in value}
    return set()


def _walk_json_ld(value: object):
    if isinstance(value, list):
        for item in value:
            yield from _walk_json_ld(item)
    elif isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if graph is not None:
            yield from _walk_json_ld(graph)
        for key in ("itemListElement", "mainEntity", "item"):
            nested = value.get(key)
            if isinstance(nested, (dict, list)):
                yield from _walk_json_ld(nested)


def _parse_json_documents(parser: RecipeHtmlParser) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for raw in parser.json_ld:
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        nodes.extend(node for node in _walk_json_ld(document) if isinstance(node, dict))
    return nodes


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    match = NUMBER_RE.search(str(value).replace(" ", " "))
    if match is None:
        return None
    try:
        return Decimal(match.group().replace(",", "."))
    except InvalidOperation:
        return None


def _yield_servings(value: object) -> tuple[Decimal | None, bool]:
    if isinstance(value, list):
        value = next((item for item in value if _decimal(item) is not None), None)
    text = str(value or "")
    numbers = [_decimal(match) for match in NUMBER_RE.findall(text)]
    numbers = [number for number in numbers if number is not None]
    is_range = len(numbers) >= 2 and bool(re.search(r"\d\s*(?:-|–|—|to)\s*\d", text, re.IGNORECASE))
    if is_range:
        return (numbers[0] + numbers[1]) / Decimal("2"), True
    return (numbers[0] if numbers else None), False


def _image(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        candidates = [item for item in (_image(item) for item in value) if item]
        return candidates[-1] if candidates else None
    if isinstance(value, dict):
        return _image(value.get("url") or value.get("contentUrl"))
    return None


def _publisher(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return str(value.get("name") or "").strip() or None
    return None


def parse_publisher_nutrition(value: object) -> PublisherNutritionPreview | None:
    if not isinstance(value, dict):
        return None
    energy_value = value.get("calories") or value.get("energy")
    energy = _decimal(energy_value)
    if energy is not None and energy_value and "kj" in str(energy_value).lower() and "kcal" not in str(energy_value).lower():
        energy = energy / Decimal("4.184")
    result = PublisherNutritionPreview(
        basis=str(value.get("servingSize") or "").strip() or "publisher basis not specified",
        energy_kcal=energy,
        protein_g=_decimal(value.get("proteinContent") or value.get("protein")),
        carbohydrate_g=_decimal(value.get("carbohydrateContent") or value.get("carbohydrates")),
        fat_g=_decimal(value.get("fatContent") or value.get("fat")),
        fibre_g=_decimal(value.get("fiberContent") or value.get("fibreContent")),
        raw={str(key): item for key, item in value.items() if isinstance(item, (str, int, float, bool))},
    )
    return result if result.available else None


def _normalise_ingredients(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, list):
        values = tuple(str(item) for item in value if isinstance(item, (str, int, float)))
    else:
        return ()
    return tuple(dict.fromkeys(unescape(" ".join(item.split())) for item in values if item.strip()))


def extract_recipe(html: str, page_url: str) -> ExtractedRecipe:
    """Extract fields present in HTML and flag anything requiring human review.

    JSON-LD Recipe markup is preferred. Semantic HTML/meta fields are a limited
    fallback and are always review-required. Cooking instructions are purposely
    not extracted for publisher recipes; the application links back to the page.
    """

    canonical_url = canonicalize_url(page_url)
    parser = RecipeHtmlParser()
    parser.feed(html)
    recipe_node = next((node for node in _parse_json_documents(parser) if "recipe" in _types(node.get("@type"))), None)

    reasons: list[str] = []
    if recipe_node is not None:
        title = unescape(str(recipe_node.get("name") or parser.h1 or parser.meta.get("og:title") or "").strip())
        ingredients = _normalise_ingredients(
            recipe_node.get("recipeIngredient") or recipe_node.get("ingredients")
        )
        servings, yield_was_range = _yield_servings(recipe_node.get("recipeYield"))
        publisher = _publisher(recipe_node.get("publisher") or recipe_node.get("author"))
        image_url = _image(recipe_node.get("image")) or parser.meta.get("og:image")
        nutrition = parse_publisher_nutrition(recipe_node.get("nutrition"))
        method = "json_ld"
        if yield_was_range:
            reasons.append("Serving yield was a range; its midpoint must be confirmed")
    else:
        title = str(parser.h1 or parser.meta.get("og:title") or "").strip()
        ingredients = parser.ingredients
        servings = None
        publisher = parser.meta.get("og:site_name")
        image_url = parser.meta.get("og:image")
        nutrition = None
        method = "semantic_html_fallback"
        reasons.append("No Schema.org Recipe JSON-LD was found; fallback fields must be checked")

    if not title:
        title = "Untitled imported recipe"
        reasons.append("Recipe title was not found")
    if not ingredients:
        reasons.append("No ingredient lines were found")
    if servings is None or servings <= 0:
        reasons.append("Serving yield is missing or invalid")
        servings = None
    if image_url:
        try:
            image_url = canonicalize_url(image_url, base_url=canonical_url)
        except Exception:
            image_url = None
            reasons.append("The recipe image URL was invalid")

    # Ingredient text is retained for the recipe and shopping features. Food
    # matching is intentionally not part of the current nutrition workflow.
    if ingredients:
        reasons.append("Ingredient amounts and units can be reviewed for shopping")
    return ExtractedRecipe(
        title=title,
        canonical_url=canonical_url,
        publisher=publisher,
        image_url=image_url,
        yield_servings=servings,
        ingredient_lines=ingredients,
        publisher_nutrition=nutrition,
        extraction_method=method,
        review_required=bool(reasons),
        review_reasons=tuple(dict.fromkeys(reasons)),
    )
