from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from fractions import Fraction
from typing import SupportsFloat


@dataclass(frozen=True, slots=True)
class QuantityRule:
    increment: Decimal
    indivisible: bool = False
    fraction_denominator: int | None = None


_WHOLE = QuantityRule(Decimal("1"), indivisible=True)
_METRIC_WHOLE = QuantityRule(Decimal("1"))
_HUNDREDTH = QuantityRule(Decimal("0.01"))
_QUARTER = QuantityRule(Decimal("0.25"), fraction_denominator=4)
_EIGHTH = QuantityRule(Decimal("0.125"), fraction_denominator=8)


QUANTITY_RULES: dict[str, QuantityRule] = {
    "g": _METRIC_WHOLE,
    "mg": _METRIC_WHOLE,
    "ml": _METRIC_WHOLE,
    "kg": _HUNDREDTH,
    "l": _HUNDREDTH,
    "oz": _HUNDREDTH,
    "lb": _HUNDREDTH,
    "tsp": _QUARTER,
    "tbsp": _QUARTER,
    "cup": _EIGHTH,
    "cm": QuantityRule(Decimal("0.1")),
    "mm": _METRIC_WHOLE,
    "m": _HUNDREDTH,
    **{
        unit: _WHOLE
        for unit in {
            "item",
            "egg",
            "clove",
            "slice",
            "bunch",
            "handful",
            "can",
            "tin",
            "jar",
            "packet",
            "pack",
            "bottle",
            "bar",
            "pot",
            "pod",
            "cube",
            "sprig",
            "stalk",
            "head",
            "fillet",
            "piece",
            "pinch",
            "dash",
            "splash",
            "drizzle",
            "small",
            "medium",
            "large",
        }
    },
}


_UNIT_ALIASES = {
    "count": "item",
    "counts": "item",
    "each": "item",
    "items": "item",
    "gram": "g",
    "grams": "g",
    "milligram": "mg",
    "milligrams": "mg",
    "kilogram": "kg",
    "kilograms": "kg",
    "millilitre": "ml",
    "millilitres": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "litre": "l",
    "litres": "l",
    "liter": "l",
    "liters": "l",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tsps": "tsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "tbsps": "tbsp",
    "cups": "cup",
    "eggs": "egg",
    "cloves": "clove",
    "slices": "slice",
    "bunches": "bunch",
    "handfuls": "handful",
    "cans": "can",
    "tins": "tin",
    "jars": "jar",
    "packets": "packet",
    "packs": "pack",
    "packages": "pack",
    "package": "pack",
    "bottles": "bottle",
    "bars": "bar",
    "pots": "pot",
    "pods": "pod",
    "cubes": "cube",
    "sprigs": "sprig",
    "stalks": "stalk",
    "heads": "head",
    "fillets": "fillet",
    "pieces": "piece",
    "pinches": "pinch",
    "dashes": "dash",
    "splashes": "splash",
    "drizzles": "drizzle",
    "centimetre": "cm",
    "centimetres": "cm",
    "centimeter": "cm",
    "centimeters": "cm",
}


_UNIT_LABELS = {
    "item": ("item", "items"),
    "egg": ("egg", "eggs"),
    "clove": ("clove", "cloves"),
    "slice": ("slice", "slices"),
    "bunch": ("bunch", "bunches"),
    "handful": ("handful", "handfuls"),
    "can": ("can", "cans"),
    "tin": ("tin", "tins"),
    "jar": ("jar", "jars"),
    "packet": ("packet", "packets"),
    "pack": ("pack", "packs"),
    "bottle": ("bottle", "bottles"),
    "bar": ("bar", "bars"),
    "pot": ("pot", "pots"),
    "pod": ("pod", "pods"),
    "cube": ("cube", "cubes"),
    "sprig": ("sprig", "sprigs"),
    "stalk": ("stalk", "stalks"),
    "head": ("head", "heads"),
    "fillet": ("fillet", "fillets"),
    "piece": ("piece", "pieces"),
    "pinch": ("pinch", "pinches"),
    "dash": ("dash", "dashes"),
    "splash": ("splash", "splashes"),
    "drizzle": ("drizzle", "drizzles"),
    "cup": ("cup", "cups"),
}


_FRACTION_GLYPHS = {
    Fraction(1, 8): "⅛",
    Fraction(1, 4): "¼",
    Fraction(3, 8): "⅜",
    Fraction(1, 2): "½",
    Fraction(5, 8): "⅝",
    Fraction(3, 4): "¾",
    Fraction(7, 8): "⅞",
}


def canonical_quantity_unit(unit: str) -> str:
    cleaned = " ".join(unit.strip().casefold().rstrip(".").split())
    return _UNIT_ALIASES.get(cleaned, cleaned)


def quantity_rule(unit: str) -> QuantityRule:
    return QUANTITY_RULES.get(canonical_quantity_unit(unit), _HUNDREDTH)


def _decimal(value: Decimal | int | str | SupportsFloat) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _round_magnitude(
    magnitude: Decimal,
    rule: QuantityRule,
    *,
    upward: bool,
) -> Decimal:
    if magnitude == 0:
        return Decimal("0")
    rounding = ROUND_CEILING if upward or rule.indivisible else ROUND_HALF_UP
    steps = (magnitude / rule.increment).to_integral_value(rounding=rounding)
    rounded = steps * rule.increment
    return rounded if rounded > 0 else rule.increment


def round_quantity(
    value: Decimal | int | str | SupportsFloat,
    unit: str,
) -> Decimal:
    """Round a stored requirement, pantry balance, reservation, or movement.

    Divisible quantities use familiar half-up rounding. Physical count units
    round away from zero because a fraction of an item cannot be stocked or
    reserved. A non-zero value is never allowed to disappear as zero.
    """

    quantity = _decimal(value)
    sign = Decimal("-1") if quantity < 0 else Decimal("1")
    return sign * _round_magnitude(abs(quantity), quantity_rule(unit), upward=False)


def round_purchase_quantity(
    value: Decimal | int | str | SupportsFloat,
    unit: str,
) -> Decimal:
    """Round a shopping amount away from zero so the list never under-buys."""

    quantity = _decimal(value)
    sign = Decimal("-1") if quantity < 0 else Decimal("1")
    return sign * _round_magnitude(abs(quantity), quantity_rule(unit), upward=True)


def _format_number(value: Decimal, rule: QuantityRule) -> str:
    if rule.fraction_denominator:
        sign = "-" if value < 0 else ""
        magnitude = abs(value)
        whole = int(magnitude)
        numerator = int(
            ((magnitude - Decimal(whole)) * rule.fraction_denominator).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )
        if numerator == rule.fraction_denominator:
            whole += 1
            numerator = 0
        fraction = Fraction(numerator, rule.fraction_denominator)
        glyph = _FRACTION_GLYPHS.get(fraction, "") if numerator else ""
        if whole and glyph:
            return f"{sign}{whole}{glyph}"
        if glyph:
            return f"{sign}{glyph}"
        return f"{sign}{whole}"

    places = max(0, -rule.increment.normalize().as_tuple().exponent)
    rendered = f"{value:,.{places}f}"
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def format_quantity(value: Decimal | int | str | SupportsFloat, unit: str) -> str:
    canonical_unit = canonical_quantity_unit(unit)
    rounded = round_quantity(value, canonical_unit)
    rendered = _format_number(rounded, quantity_rule(canonical_unit))
    singular, plural = _UNIT_LABELS.get(canonical_unit, (canonical_unit, canonical_unit))
    magnitude = abs(rounded)
    label = singular if Decimal("0") < magnitude <= Decimal("1") else plural
    return f"{rendered} {label}".strip()
