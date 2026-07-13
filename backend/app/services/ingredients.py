from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re


@dataclass(frozen=True, slots=True)
class ParsedIngredient:
    quantity: Decimal | None
    unit: str | None
    quantity_grams: Decimal | None
    food_phrase: str
    preparation: str | None = None
    optional: bool = False


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
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "cup": "cup", "cups": "cup",
    "clove": "clove", "cloves": "clove",
    "slice": "slice", "slices": "slice",
    "bunch": "bunch", "bunches": "bunch",
    "handful": "handful", "handfuls": "handful",
    "can": "can", "cans": "can", "tin": "tin", "tins": "tin",
    "jar": "jar", "jars": "jar", "packet": "packet", "packets": "packet",
    "pack": "pack", "packs": "pack", "package": "pack", "packages": "pack",
    "bottle": "bottle", "bottles": "bottle",
    "sprig": "sprig", "sprigs": "sprig", "stalk": "stalk", "stalks": "stalk",
    "head": "head", "heads": "head", "fillet": "fillet", "fillets": "fillet",
    "piece": "piece", "pieces": "piece", "pinch": "pinch", "pinches": "pinch",
    "dash": "dash", "dashes": "dash", "splash": "splash", "splashes": "splash",
    "small": "small", "medium": "medium", "large": "large",
}
_PREPARATION_WORDS = {
    "chopped", "diced", "sliced", "minced", "crushed", "grated", "peeled",
    "drained", "rinsed", "melted", "softened", "beaten", "divided", "cooked",
    "uncooked", "zested", "juiced", "trimmed", "shredded", "quartered",
}


def _normalise_fractions(text: str) -> str:
    for symbol, replacement in _UNICODE_FRACTIONS.items():
        text = re.sub(rf"(?<=\d){re.escape(symbol)}", f" {replacement}", text)
        text = text.replace(symbol, replacement)
    return text.replace("\u00a0", " ")


def _decimal(value: str) -> Decimal | None:
    value = value.strip().replace(",", ".")
    try:
        if " " in value and "/" in value:
            whole, fraction = value.split(None, 1)
            numerator, denominator = fraction.split("/", 1)
            return Decimal(whole) + Decimal(numerator) / Decimal(denominator)
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return Decimal(numerator) / Decimal(denominator)
        return Decimal(value)
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None


def _clean_food_phrase(value: str) -> tuple[str, str | None]:
    value = re.sub(r"^[\s,;:-]*(?:of\s+)?", "", value, flags=re.IGNORECASE)
    parts = [part.strip(" ,;:-") for part in value.split(",", 1)]
    phrase = parts[0]
    preparation = parts[1] if len(parts) > 1 and parts[1] else None
    if preparation is None:
        words = phrase.split()
        trailing: list[str] = []
        while words and words[-1].casefold().strip("().") in _PREPARATION_WORDS:
            trailing.insert(0, words.pop())
        if trailing and words:
            phrase = " ".join(words)
            preparation = " ".join(trailing)
    phrase = re.sub(r"\s+", " ", phrase).strip(" .")
    return phrase or value.strip() or "Ingredient", preparation


def parse_ingredient(text: str) -> ParsedIngredient:
    """Parse the amount/unit already written by the recipe without inventing a weight.

    Count and descriptive units are preserved (for example ``clove`` or
    ``large``). A gram amount is populated only when the source explicitly gives
    a mass, including common multipacks such as ``2 x 400g tins``.
    """

    original = " ".join(_normalise_fractions(text).split()).strip()
    optional = bool(re.search(r"\boptional\b", original, re.IGNORECASE))

    multipack = re.match(
        rf"^(?P<count>{_NUMBER})\s*[x×]\s*(?P<size>{_NUMBER})\s*(?P<size_unit>[A-Za-z]+)\b"
        rf"(?:\s+(?P<pack>cans?|tins?|jars?|packets?|packs?|packages?|bottles?))?\s*(?P<rest>.*)$",
        original,
        re.IGNORECASE,
    )
    if multipack:
        count = _decimal(multipack.group("count"))
        size = _decimal(multipack.group("size"))
        size_unit = _UNIT_ALIASES.get(multipack.group("size_unit").casefold())
        pack = multipack.group("pack")
        unit = _UNIT_ALIASES.get(pack.casefold()) if pack else size_unit
        grams = count * size * _MASS_FACTORS[size_unit] if count is not None and size is not None and size_unit in _MASS_FACTORS else None
        phrase, preparation = _clean_food_phrase(multipack.group("rest"))
        return ParsedIngredient(count, unit, grams, phrase, preparation, optional)

    amount_match = re.match(rf"^(?P<amount>{_NUMBER})\s*(?P<rest>.*)$", original, re.IGNORECASE)
    if amount_match:
        quantity = _decimal(amount_match.group("amount"))
        rest = amount_match.group("rest").lstrip()
        unit_match = re.match(r"^(?P<unit>[A-Za-z]+)\.?\b\s*(?P<rest>.*)$", rest)
        raw_unit = unit_match.group("unit").casefold() if unit_match else ""
        unit = _UNIT_ALIASES.get(raw_unit)
        if unit_match and unit:
            rest = unit_match.group("rest")
        else:
            unit = "item"
        phrase, preparation = _clean_food_phrase(rest)
        grams = quantity * _MASS_FACTORS[unit] if quantity is not None and unit in _MASS_FACTORS else None
        return ParsedIngredient(quantity, unit, grams, phrase, preparation, optional)

    descriptive = re.match(
        r"^(?:an?\s+)?(?P<unit>pinch|dash|splash|handful)\s+(?:of\s+)?(?P<rest>.+)$",
        original,
        re.IGNORECASE,
    )
    if descriptive:
        phrase, preparation = _clean_food_phrase(descriptive.group("rest"))
        return ParsedIngredient(None, _UNIT_ALIASES[descriptive.group("unit").casefold()], None, phrase, preparation, optional)

    phrase, preparation = _clean_food_phrase(original)
    return ParsedIngredient(None, None, None, phrase, preparation, optional)


def food_search_phrase(text: str) -> str:
    parsed = parse_ingredient(text)
    phrase = re.sub(r"\([^)]*\)", " ", parsed.food_phrase)
    words = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z'-]+", phrase.casefold())
        if word not in _PREPARATION_WORDS and word not in {"fresh", "optional", "roughly", "finely", "plus", "extra"}
    ]
    return " ".join(words[:8])
