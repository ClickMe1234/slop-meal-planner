from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .quantities import canonical_quantity_unit


FAO_INFOODS_DENSITY_SOURCE = (
    "FAO/INFOODS Density Database, version 2.0 (2012), CC BY 4.0"
)
FAO_INFOODS_DENSITY_URL = (
    "https://www.fao.org/food-composition/tables-and-databases/"
    "detail/%28global--2012%29-fao-infoods-density-database---version-2/en"
)
USDA_FDC_SOURCE = (
    "USDA FoodData Central, SR Legacy April 2018, public domain (CC0 1.0)"
)
USDA_FDC_URL = "https://fdc.nal.usda.gov/download-datasets/"


@dataclass(frozen=True, slots=True)
class IngredientMeasurementProfile:
    """A reviewed shopping-unit choice and a culinary bulk density."""

    canonical_name: str
    density_g_per_ml: Decimal
    preferred_shopping_unit: str
    aliases: tuple[str, ...]
    source: str
    source_url: str
    source_reference: str


def _profile(
    canonical_name: str,
    density: str,
    preferred_unit: str,
    *aliases: str,
    source: str = FAO_INFOODS_DENSITY_SOURCE,
    reference: str,
) -> IngredientMeasurementProfile:
    return IngredientMeasurementProfile(
        canonical_name=canonical_name,
        density_g_per_ml=Decimal(density),
        preferred_shopping_unit=preferred_unit,
        aliases=tuple(dict.fromkeys((canonical_name, *aliases))),
        source=source,
        source_url=(USDA_FDC_URL if source == USDA_FDC_SOURCE else FAO_INFOODS_DENSITY_URL),
        source_reference=reference,
    )


# This is deliberately a reviewed registry rather than a fuzzy lookup.  Bulk
# densities vary with preparation and packing, so a false positive is worse
# than leaving an unsupported ingredient as separate mass and volume lines.
# FAO ranges use their midpoint; USDA entries use the gram weight of a 240 ml
# household cup (or an equivalent household measure).
INGREDIENT_MEASUREMENT_PROFILES: tuple[IngredientMeasurementProfile, ...] = (
    # Freely pourable liquids are presented in ml.
    _profile("water", "1", "ml", source=FAO_INFOODS_DENSITY_SOURCE, reference="Water"),
    _profile(
        "milk", "1.03", "ml", "whole milk", "semi-skimmed milk", "skimmed milk",
        reference="Milk, liquid (whole, semi-skimmed, skimmed)",
    ),
    _profile("buttermilk", "1.022", "ml", reference="Milk, buttermilk"),
    _profile(
        "cream", "0.99", "ml", "single cream", "double cream", "heavy cream",
        "whipping cream", reference="Cream, liquid varieties",
    ),
    _profile(
        "cooking oil", "0.92", "ml", "oil", "vegetable oil", "neutral oil",
        reference="Cooking oil / oil other than palm oil",
    ),
    _profile("olive oil", "0.918", "ml", "extra virgin olive oil", reference="Oil, vegetable, olive"),
    _profile("rapeseed oil", "0.92", "ml", "canola oil", reference="Oil, rapeseed (at 20 C)"),
    _profile("sunflower oil", "0.92", "ml", reference="Oil, sunflower; reviewed culinary midpoint"),
    _profile("coconut oil", "0.924", "ml", reference="Oil, vegetable, coconut"),
    _profile("sesame oil", "0.923", "ml", reference="Oil, sesame seed (at 15.6 C)"),
    _profile(
        "vinegar", "1.01", "ml", "white vinegar", "cider vinegar", "apple cider vinegar",
        "red wine vinegar", "white wine vinegar", reference="Reviewed USDA household portions",
        source=USDA_FDC_SOURCE,
    ),
    _profile(
        "stock", "1", "ml", "broth", "chicken stock", "vegetable stock", "beef stock",
        "chicken broth", "vegetable broth", "beef broth", reference="Reviewed USDA household portions",
        source=USDA_FDC_SOURCE,
    ),
    _profile(
        "fruit juice", "1.06", "ml", "juice", "apple juice", "orange juice", "lemon juice",
        "lime juice", reference="Fruit juice",
    ),
    _profile("wine", "0.99", "ml", "red wine", "white wine", reference="Wine, table"),
    _profile("soy sauce", "1.12", "ml", "soya sauce", reference="Sauce, soy"),
    _profile(
        "vanilla extract", "0.88", "ml", "vanilla essence", reference="FDC household portion for vanilla extract",
        source=USDA_FDC_SOURCE,
    ),

    # Dry, solid, or thick ingredients are presented in g.
    _profile(
        "plain flour", "0.521", "g", "flour", "all-purpose flour", "all purpose flour",
        "white flour", "wheat flour", reference="Wheat, flour (S&W); FDC 169761 cross-check",
    ),
    _profile("wholemeal flour", "0.55", "g", "whole wheat flour", reference="Wheat, flour, wholemeal"),
    _profile(
        "self-raising flour", "0.521", "g", "self-rising flour", "self raising flour",
        "self rising flour", reference="FDC household portion; plain flour bulk-density proxy",
        source=USDA_FDC_SOURCE,
    ),
    _profile("bread flour", "0.542", "g", "strong flour", "strong white flour", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("oat flour", "0.53", "g", reference="Oat flour"),
    _profile("almond flour", "0.40", "g", "ground almonds", "almond meal", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("cornflour", "0.54", "g", "cornstarch", "corn starch", reference="Corn/maize starch, loosely packed"),
    _profile("granulated sugar", "0.833", "g", "sugar", "white sugar", "caster sugar", "castor sugar", reference="FDC household portions; FAO sugar range", source=USDA_FDC_SOURCE),
    _profile("icing sugar", "0.50", "g", "powdered sugar", "confectioners sugar", "confectioner's sugar", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("brown sugar", "0.888", "g", "light brown sugar", "dark brown sugar", "muscovado sugar", reference="FDC packed household portion", source=USDA_FDC_SOURCE),
    _profile("butter", "0.946", "g", "salted butter", "unsalted butter", reference="FDC 173410 household portions", source=USDA_FDC_SOURCE),
    _profile("margarine", "0.96", "g", reference="Butter, margarine"),
    _profile("honey", "1.40", "g", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("maple syrup", "1.32", "g", reference="Syrup, maple"),
    _profile("golden syrup", "1.38", "g", "corn syrup", reference="Syrup, corn; reviewed equivalent"),
    _profile("molasses", "1.40", "g", "black treacle", "treacle", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("cocoa powder", "0.354", "g", "cacao powder", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("baking powder", "0.90", "g", reference="Baking powder"),
    _profile("bicarbonate of soda", "0.92", "g", "baking soda", "sodium bicarbonate", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("table salt", "1.217", "g", "salt", "fine salt", reference="Salt, table"),
    _profile("yeast", "0.62", "g", "dried yeast", "dry yeast", "instant yeast", "active dry yeast", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("rolled oats", "0.34", "g", "oats", "porridge oats", reference="Oats, rolled (range midpoint)"),
    _profile("raw rice", "0.82", "g", "rice", "white rice", "long grain rice", "basmati rice", "jasmine rice", reference="Rice, white, raw"),
    _profile("cooked rice", "0.73", "g", "boiled rice", reference="Rice, white, boiled"),
    _profile("breadcrumbs", "0.45", "g", "bread crumbs", reference="Breadcrumbs"),
    _profile("panko breadcrumbs", "0.25", "g", "panko", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("peanut butter", "1.18", "g", "smooth peanut butter", "crunchy peanut butter", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("yoghurt", "1.045", "g", "yogurt", "plain yoghurt", "plain yogurt", "greek yoghurt", "greek yogurt", reference="Yoghurt, plain / fruit range midpoint"),
    _profile("mayonnaise", "0.91", "g", "mayo", reference="Mayonnaise, traditional"),
    _profile("jam", "1.333", "g", "preserve", reference="Jam"),
    _profile("chocolate hazelnut spread", "1.26", "g", "nutella", reference="Nutella"),
    _profile("tomato puree", "1.08", "g", "tomato paste", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("short pasta", "0.39", "g", "macaroni", "penne", "fusilli", reference="Pasta, short macaroni style, raw"),
    _profile("lentils", "0.89", "g", "green lentils", "dry lentils", reference="Lentils, green, small, raw"),
    _profile("almonds", "0.46", "g", reference="Almonds"),
    _profile("cashews", "0.50", "g", reference="Cashews"),
    _profile("flaxseed", "0.70", "g", "linseed", reference="Flaxseed"),
    _profile("cinnamon", "0.56", "g", "ground cinnamon", "cinnamon powder", reference="Cinnamon, powder"),
    _profile("garlic powder", "0.32", "g", reference="Garlic, powder"),
)


_PUNCTUATION = re.compile(r"[^a-z0-9]+")
_ALIASES: dict[str, IngredientMeasurementProfile] = {}


def normalise_measurement_name(value: str) -> str:
    return " ".join(_PUNCTUATION.sub(" ", value.casefold()).split())


for _entry in INGREDIENT_MEASUREMENT_PROFILES:
    if _entry.preferred_shopping_unit not in {"g", "ml"}:
        raise ValueError(f"Unsupported shopping unit for {_entry.canonical_name}")
    if _entry.density_g_per_ml <= 0:
        raise ValueError(f"Invalid density for {_entry.canonical_name}")
    for _alias in _entry.aliases:
        _key = normalise_measurement_name(_alias)
        if _key in _ALIASES and _ALIASES[_key] is not _entry:
            raise ValueError(f"Duplicate ingredient measurement alias: {_alias}")
        _ALIASES[_key] = _entry


VOLUME_TO_ML: dict[str, Decimal] = {
    "ml": Decimal("1"),
    "l": Decimal("1000"),
    "tsp": Decimal("5"),
    "tbsp": Decimal("15"),
    "cup": Decimal("240"),
}

MASS_TO_G: dict[str, Decimal] = {
    "mg": Decimal("0.001"),
    "g": Decimal("1"),
    "kg": Decimal("1000"),
    "oz": Decimal("28.3495"),
    "lb": Decimal("453.59237"),
}


def resolve_measurement_profile(*names: str | None) -> IngredientMeasurementProfile | None:
    """Return a profile only for a reviewed exact alias."""

    for name in names:
        if name and (profile := _ALIASES.get(normalise_measurement_name(name))):
            return profile
    return None


def measurement_dimension(unit: str) -> str | None:
    canonical = canonical_quantity_unit(unit)
    if canonical in MASS_TO_G:
        return "mass"
    if canonical in VOLUME_TO_ML:
        return "volume"
    return None


def convert_quantity_to_unit(
    quantity: Decimal,
    unit: str,
    target_unit: str,
    density_g_per_ml: Decimal | None,
) -> Decimal | None:
    """Convert compatible shopping quantities without guessing a density."""

    canonical = canonical_quantity_unit(unit)
    target = canonical_quantity_unit(target_unit)
    if canonical == target:
        return Decimal(quantity)
    if canonical in MASS_TO_G:
        grams = Decimal(quantity) * MASS_TO_G[canonical]
        if target == "g":
            return grams
        if target == "ml" and density_g_per_ml:
            return grams / density_g_per_ml
        return None
    if canonical in VOLUME_TO_ML:
        millilitres = Decimal(quantity) * VOLUME_TO_ML[canonical]
        if target == "ml":
            return millilitres
        if target == "g" and density_g_per_ml:
            return millilitres * density_g_per_ml
        return None
    return None


def normalise_shopping_measurement(
    quantity: Decimal,
    unit: str,
    profile: IngredientMeasurementProfile | None,
    *,
    density_override: Decimal | None = None,
) -> tuple[Decimal, str]:
    """Choose the shopping dimension and normalize the amount into g or ml."""

    canonical = canonical_quantity_unit(unit)
    dimension = measurement_dimension(canonical)
    if dimension is None:
        return Decimal(quantity), canonical
    density = density_override or (profile.density_g_per_ml if profile else None)
    target = profile.preferred_shopping_unit if profile else ("g" if dimension == "mass" else "ml")
    converted = convert_quantity_to_unit(Decimal(quantity), canonical, target, density)
    if converted is None:
        fallback = "g" if dimension == "mass" else "ml"
        converted = convert_quantity_to_unit(Decimal(quantity), canonical, fallback, None)
        return (converted if converted is not None else Decimal(quantity)), fallback
    return converted, target
