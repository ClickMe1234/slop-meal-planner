from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import re
from typing import Any

from ingredient_parser import parse_ingredient as parse_nlp_ingredient


PARSER_VERSION = "ingredient-parser-nlp-2.7.0+adapter1"
MIN_NAME_CONFIDENCE = 0.75


@dataclass(frozen=True, slots=True)
class ParsedIngredient:
    quantity: Decimal | None
    unit: str | None
    quantity_grams: Decimal | None
    food_phrase: str
    preparation: str | None = None
    optional: bool = False
    name_confidence: float | None = None
    needs_review: bool = False


_UNICODE_FRACTIONS = {
    "¼": "1/4",
    "½": "1/2",
    "¾": "3/4",
    "⅓": "1/3",
    "⅔": "2/3",
    "⅕": "1/5",
    "⅖": "2/5",
    "⅗": "3/5",
    "⅘": "4/5",
    "⅙": "1/6",
    "⅚": "5/6",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}
_NUMBER = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)"
_MASS_FACTORS = {
    "g": Decimal("1"),
    "kg": Decimal("1000"),
    "mg": Decimal("0.001"),
    "oz": Decimal("28.3495"),
    "lb": Decimal("453.59237"),
}
_UNIT_ALIASES = {
    "g": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "ml": "ml", "millilitre": "ml", "millilitres": "ml", "milliliter": "ml", "milliliters": "ml",
    "l": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "tsp": "tsp", "tsps": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "tbsp": "tbsp", "tbsps": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "cup": "cup", "cups": "cup",
    "clove": "clove", "cloves": "clove",
    "slice": "slice", "slices": "slice",
    "bunch": "bunch", "bunches": "bunch",
    "handful": "handful", "handfuls": "handful",
    "can": "can", "cans": "can", "tin": "tin", "tins": "tin",
    "jar": "jar", "jars": "jar", "packet": "packet", "packets": "packet",
    "pack": "pack", "packs": "pack", "package": "pack", "packages": "pack",
    "bottle": "bottle", "bottles": "bottle", "bar": "bar", "bars": "bar",
    "pot": "pot", "pots": "pot", "pod": "pod", "pods": "pod",
    "cube": "cube", "cubes": "cube",
    "sprig": "sprig", "sprigs": "sprig", "stalk": "stalk", "stalks": "stalk",
    "head": "head", "heads": "head", "fillet": "fillet", "fillets": "fillet",
    "piece": "piece", "pieces": "piece", "pinch": "pinch", "pinches": "pinch",
    "dash": "dash", "dashes": "dash", "splash": "splash", "splashes": "splash",
    "drizzle": "drizzle", "drizzles": "drizzle",
    "cm": "cm", "centimetre": "cm", "centimetres": "cm", "centimeter": "cm", "centimeters": "cm",
    "mm": "mm", "m": "m",
    "small": "small", "medium": "medium", "large": "large",
}
_PACK_UNITS = {
    "can", "tin", "jar", "packet", "pack", "bottle", "bar", "pot",
}
_DESCRIPTIVE_UNITS = {
    "pinch", "dash", "splash", "drizzle", "handful", "sprig", "stalk", "bunch",
}
_NON_IDENTITY_MODIFIERS = {
    "bashed", "beaten", "boneless", "chopped", "cored", "crushed", "cubed",
    "deseeded", "diced", "divided", "drained", "grated", "halved", "juiced",
    "melted", "minced", "peeled", "quartered", "rinsed", "shredded", "skinned",
    "skinless", "sliced", "softened", "toasted", "trimmed", "zested",
}
_PREPARATION_ADVERBS = {"coarsely", "finely", "roughly", "thinly"}


def _normalise_fractions(text: str) -> str:
    for symbol, replacement in _UNICODE_FRACTIONS.items():
        text = re.sub(rf"(?<=\d){re.escape(symbol)}", f" {replacement}", text)
        text = text.replace(symbol, replacement)
    return text.replace("\u00a0", " ")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    raw = str(value).strip().replace(",", ".")
    try:
        if " " in raw and "/" in raw:
            whole, fraction = raw.split(None, 1)
            numerator, denominator = fraction.split("/", 1)
            return Decimal(whole) + Decimal(numerator) / Decimal(denominator)
        if "/" in raw:
            numerator, denominator = raw.split("/", 1)
            return Decimal(numerator) / Decimal(denominator)
        return Decimal(raw)
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None


def _canonical_unit(raw: Any) -> str | None:
    value = re.sub(r"[^a-z ]", "", str(raw or "").casefold()).strip()
    if not value:
        return None
    if value in _UNIT_ALIASES:
        return _UNIT_ALIASES[value]
    words = value.split()
    for word in words:
        if word in _MASS_FACTORS:
            return word
    if words and words[-1] in _UNIT_ALIASES:
        canonical = _UNIT_ALIASES[words[-1]]
        if len(words) > 1 and canonical in _DESCRIPTIVE_UNITS:
            return f"{' '.join(words[:-1])} {canonical}"[:40]
        return canonical
    return None


def _strip_non_identity_modifiers(value: str) -> tuple[str, list[str]]:
    phrase = re.sub(r"\s+", " ", value).strip(" ,;:-.")
    removed: list[str] = []
    modifiers = "|".join(sorted(map(re.escape, _NON_IDENTITY_MODIFIERS), key=len, reverse=True))
    adverbs = "|".join(sorted(map(re.escape, _PREPARATION_ADVERBS), key=len, reverse=True))
    leading = re.compile(
        rf"^(?:(?P<adverb>{adverbs})\s+)?(?P<modifier>{modifiers})\b[\s,;:-]*",
        re.IGNORECASE,
    )
    while match := leading.match(phrase):
        removed.extend(value for value in (match.group("adverb"), match.group("modifier")) if value)
        phrase = phrase[match.end():].strip(" ,;:-.")
    trailing = re.compile(
        rf"[\s,;:-]+(?:(?P<adverb>{adverbs})\s+)?(?P<modifier>{modifiers})$",
        re.IGNORECASE,
    )
    while match := trailing.search(phrase):
        removed[0:0] = [value for value in (match.group("adverb"), match.group("modifier")) if value]
        phrase = phrase[:match.start()].strip(" ,;:-.")
    return phrase, removed


def _semantic_parse(original: str) -> tuple[str, str | None, float | None, bool, Any | None]:
    try:
        parsed = parse_nlp_ingredient(
            original,
            string_units=True,
            separate_names=True,
        )
    except Exception:
        return original or "Ingredient", None, None, True, None

    descriptive = re.match(
        rf"^(?:an?|one)?\s*(?:small|medium|large)?\s*(?:{'|'.join(_DESCRIPTIVE_UNITS)})s?\s+(?:of\s+)?(?P<rest>.+)$",
        original,
        re.IGNORECASE,
    )
    names = sorted(parsed.name, key=lambda item: item.starting_index)
    cleaned: list[str] = []
    removed: list[str] = []
    confidences: list[float] = []
    for item in names:
        phrase, item_removed = _strip_non_identity_modifiers(item.text)
        if phrase and phrase.casefold() not in {value.casefold() for value in cleaned}:
            cleaned.append(phrase)
            confidences.append(float(item.confidence))
        removed.extend(item_removed)

    confidence = min(confidences) if confidences else None
    if descriptive:
        rest, rest_removed = _strip_non_identity_modifiers(descriptive.group("rest"))
        if rest:
            cleaned = [rest]
            # This grammar is deliberately narrow ("a sprig of thyme", "one
            # handful mint") and gives us a stronger name boundary than the
            # statistical tagger sometimes reports for short herb names.
            confidence = max(confidence or 0, 0.95)
        removed.extend(rest_removed)

    needs_review = not cleaned or len(cleaned) != 1 or confidence is None or confidence < MIN_NAME_CONFIDENCE
    if not cleaned:
        cleaned = [original or "Ingredient"]
    if len(cleaned) == 1:
        food_phrase = cleaned[0]
    else:
        connector = " or " if re.search(r"\bor\b", original, re.IGNORECASE) else " and "
        food_phrase = connector.join(cleaned)

    preparation_parts: list[str] = []
    if removed:
        preparation_parts.append(" ".join(dict.fromkeys(value.casefold() for value in removed)))
    if parsed.preparation is not None and parsed.preparation.text:
        preparation_parts.append(parsed.preparation.text)
    preparation = ", ".join(dict.fromkeys(part for part in preparation_parts if part)) or None
    return food_phrase, preparation, confidence, needs_review, parsed


def _amount_from_parse(original: str, parsed: Any | None) -> tuple[Decimal | None, str | None, Decimal | None]:
    multipack = re.match(
        rf"^(?P<count>{_NUMBER})\s*[x×]\s*(?P<size>{_NUMBER})\s*(?P<size_unit>[A-Za-z]+)\b"
        rf"(?:\s+(?P<pack>cans?|tins?|jars?|packets?|packs?|packages?|bottles?|bars?|pots?))?\s*",
        original,
        re.IGNORECASE,
    )
    if multipack:
        count = _decimal(multipack.group("count"))
        size = _decimal(multipack.group("size"))
        size_unit = _canonical_unit(multipack.group("size_unit"))
        pack = _canonical_unit(multipack.group("pack")) if multipack.group("pack") else None
        grams = (
            count * size * _MASS_FACTORS[size_unit]
            if count is not None and size is not None and size_unit in _MASS_FACTORS
            else None
        )
        return count, pack or size_unit, grams

    amounts: list[tuple[Any, Decimal, str | None, str]] = []
    for amount in getattr(parsed, "amount", []) if parsed is not None else []:
        quantity = _decimal(getattr(amount, "quantity", None))
        if quantity is None:
            continue
        raw_unit = str(getattr(amount, "unit", "") or "")
        amounts.append((amount, quantity, _canonical_unit(raw_unit), raw_unit.casefold()))

    mass = next((entry for entry in amounts if entry[2] in _MASS_FACTORS), None)
    count = next((entry for entry in amounts if entry is not mass and entry[2] not in _MASS_FACTORS), None)
    multiplier = next((entry for entry in amounts if bool(getattr(entry[0], "MULTIPLIER", False))), None)
    if mass is not None:
        grams = mass[1] * _MASS_FACTORS[mass[2]]
        if multiplier is not None and multiplier is not mass:
            grams *= multiplier[1]
        pack = count[2] if count is not None and count[2] else None
        if pack is None:
            pack_match = re.search(r"\b(cans?|tins?|jars?|packets?|packs?|packages?|bottles?|bars?|pots?)\b", mass[3])
            pack = _canonical_unit(pack_match.group(1)) if pack_match else None
        if pack:
            return (multiplier or count or (None, Decimal("1"), None, ""))[1], pack, grams
        return mass[1], mass[2], grams

    if amounts:
        first = amounts[0]
        unit = first[2]
        if unit is None:
            size = str(getattr(getattr(parsed, "size", None), "text", "") or "").casefold()
            unit = size if size in {"small", "medium", "large"} else "item"
        return first[1], unit, None

    size_text = str(getattr(getattr(parsed, "size", None), "text", "") or "") if parsed is not None else ""
    size_match = re.match(rf"^(?P<amount>{_NUMBER})\s*(?P<unit>cm|mm|m)\b", size_text, re.IGNORECASE)
    if size_match:
        return _decimal(size_match.group("amount")), size_match.group("unit").casefold(), None

    descriptive = re.match(
        rf"^(?:an?|one)?\s*(?:small|medium|large)?\s*(?P<unit>{'|'.join(_DESCRIPTIVE_UNITS)})s?\b",
        original,
        re.IGNORECASE,
    )
    if descriptive:
        return Decimal("1"), _UNIT_ALIASES[descriptive.group("unit").casefold()], None
    return None, None, None


def parse_ingredient(text: str) -> ParsedIngredient:
    """Parse a free-form English ingredient without inventing a mass.

    A local ingredient-language model separates the ingredient name from
    preparation text. Deterministic adaptation keeps the application's unit
    conventions and only calculates grams when a mass is explicitly present.
    """

    original = " ".join(_normalise_fractions(text).split()).strip()
    optional = bool(re.search(r"\boptional\b", original, re.IGNORECASE))
    food_phrase, preparation, confidence, needs_review, parsed = _semantic_parse(original)
    quantity, unit, grams = _amount_from_parse(original, parsed)
    food_phrase = re.sub(r"\s+", " ", food_phrase).strip(" .") or original or "Ingredient"
    return ParsedIngredient(
        quantity,
        unit,
        grams,
        food_phrase,
        preparation,
        optional,
        confidence,
        needs_review,
    )


def food_search_phrase(text: str) -> str:
    parsed = parse_ingredient(text)
    phrase = re.sub(r"\([^)]*\)", " ", parsed.food_phrase)
    words = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z'-]+", phrase.casefold())
        if word not in {"fresh", "optional", "roughly", "finely", "plus", "extra"}
    ]
    return " ".join(words[:8])
