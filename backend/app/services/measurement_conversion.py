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
HEALTH_CANADA_SOURCE = "Health Canada, Canadian Nutrient File"
HEALTH_CANADA_CHIA_URL = (
    "https://aliments-nutrition.canada.ca/cnf-fce/serving-portion?id=2511"
)


@dataclass(frozen=True, slots=True)
class IngredientMeasurementProfile:
    """A reviewed culinary bulk density and its provenance."""

    canonical_name: str
    density_g_per_ml: Decimal
    aliases: tuple[str, ...]
    source: str
    source_url: str
    source_reference: str


def _profile(
    canonical_name: str,
    density: str,
    *aliases: str,
    source: str = FAO_INFOODS_DENSITY_SOURCE,
    source_url: str | None = None,
    reference: str,
) -> IngredientMeasurementProfile:
    return IngredientMeasurementProfile(
        canonical_name=canonical_name,
        density_g_per_ml=Decimal(density),
        aliases=tuple(dict.fromkeys((canonical_name, *aliases))),
        source=source,
        source_url=source_url or (
            USDA_FDC_URL if source == USDA_FDC_SOURCE else FAO_INFOODS_DENSITY_URL
        ),
        source_reference=reference,
    )


# This is deliberately a reviewed registry rather than a fuzzy lookup.  Bulk
# densities vary with preparation and packing, so a false positive is worse
# than leaving an unsupported ingredient as separate mass and volume lines.
# FAO ranges use their midpoint; USDA entries use the gram weight of a 240 ml
# household cup (or an equivalent household measure).
INGREDIENT_MEASUREMENT_PROFILES: tuple[IngredientMeasurementProfile, ...] = (
    # Liquids.
    _profile("water", "1", source=FAO_INFOODS_DENSITY_SOURCE, reference="Water"),
    _profile(
        "milk", "1.03", "whole milk", "semi-skimmed milk", "skimmed milk",
        reference="Milk, liquid (whole, semi-skimmed, skimmed)",
    ),
    _profile("buttermilk", "1.022", reference="Milk, buttermilk"),
    _profile(
        "cream", "0.99", "single cream", "double cream", "heavy cream",
        "whipping cream", reference="Cream, liquid varieties",
    ),
    _profile(
        "cooking oil", "0.92", "oil", "vegetable oil", "neutral oil",
        reference="Cooking oil / oil other than palm oil",
    ),
    _profile("olive oil", "0.918", "extra virgin olive oil", reference="Oil, vegetable, olive"),
    _profile("rapeseed oil", "0.92", "canola oil", reference="Oil, rapeseed (at 20 C)"),
    _profile("sunflower oil", "0.92", reference="Oil, sunflower; reviewed culinary midpoint"),
    _profile("coconut oil", "0.924", reference="Oil, vegetable, coconut"),
    _profile("sesame oil", "0.923", reference="Oil, sesame seed (at 15.6 C)"),
    _profile(
        "vinegar", "1.01", "white vinegar", "cider vinegar", "apple cider vinegar",
        "red wine vinegar", "white wine vinegar", reference="Reviewed USDA household portions",
        source=USDA_FDC_SOURCE,
    ),
    _profile(
        "stock", "1", "broth", "chicken stock", "vegetable stock", "beef stock",
        "chicken broth", "vegetable broth", "beef broth", reference="Reviewed USDA household portions",
        source=USDA_FDC_SOURCE,
    ),
    _profile(
        "fruit juice", "1.06", "juice", "apple juice", "orange juice", "lemon juice",
        "lime juice", reference="Fruit juice",
    ),
    _profile("wine", "0.99", "red wine", "white wine", reference="Wine, table"),
    _profile("soy sauce", "1.12", "soya sauce", reference="Sauce, soy"),
    _profile(
        "vanilla extract", "0.88", "vanilla essence", reference="FDC household portion for vanilla extract",
        source=USDA_FDC_SOURCE,
    ),

    # Dry, solid, or thick ingredients.
    _profile(
        "plain flour", "0.521", "flour", "all-purpose flour", "all purpose flour",
        "white flour", "wheat flour", reference="Wheat, flour (S&W); FDC 169761 cross-check",
    ),
    _profile("wholemeal flour", "0.55", "whole wheat flour", reference="Wheat, flour, wholemeal"),
    _profile(
        "self-raising flour", "0.521", "self-rising flour", "self raising flour",
        "self rising flour", reference="FDC household portion; plain flour bulk-density proxy",
        source=USDA_FDC_SOURCE,
    ),
    _profile("bread flour", "0.542", "strong flour", "strong white flour", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("oat flour", "0.53", reference="Oat flour"),
    _profile("almond flour", "0.40", "ground almonds", "almond meal", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("cornflour", "0.54", "cornstarch", "corn starch", reference="Corn/maize starch, loosely packed"),
    _profile("granulated sugar", "0.833", "sugar", "white sugar", "caster sugar", "castor sugar", reference="FDC household portions; FAO sugar range", source=USDA_FDC_SOURCE),
    _profile("icing sugar", "0.50", "powdered sugar", "confectioners sugar", "confectioner's sugar", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("brown sugar", "0.888", "light brown sugar", "dark brown sugar", "muscovado sugar", reference="FDC packed household portion", source=USDA_FDC_SOURCE),
    _profile("butter", "0.946", "salted butter", "unsalted butter", reference="FDC 173410 household portions", source=USDA_FDC_SOURCE),
    _profile("margarine", "0.96", reference="Butter, margarine"),
    _profile("honey", "1.40", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("maple syrup", "1.32", reference="Syrup, maple"),
    _profile("golden syrup", "1.38", "corn syrup", reference="Syrup, corn; reviewed equivalent"),
    _profile("molasses", "1.40", "black treacle", "treacle", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("cocoa powder", "0.354", "cacao powder", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("baking powder", "0.90", reference="Baking powder"),
    _profile("bicarbonate of soda", "0.92", "baking soda", "sodium bicarbonate", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("table salt", "1.217", "salt", "fine salt", reference="Salt, table"),
    _profile("yeast", "0.62", "dried yeast", "dry yeast", "instant yeast", "active dry yeast", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("rolled oats", "0.34", "oats", "porridge oats", reference="Oats, rolled (range midpoint)"),
    _profile("raw rice", "0.82", "rice", "white rice", "long grain rice", "basmati rice", "jasmine rice", reference="Rice, white, raw"),
    _profile("cooked rice", "0.73", "boiled rice", reference="Rice, white, boiled"),
    _profile("breadcrumbs", "0.45", "bread crumbs", reference="Breadcrumbs"),
    _profile("panko breadcrumbs", "0.25", "panko", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("peanut butter", "1.18", "smooth peanut butter", "crunchy peanut butter", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("yoghurt", "1.045", "yogurt", "plain yoghurt", "plain yogurt", "greek yoghurt", "greek yogurt", reference="Yoghurt, plain / fruit range midpoint"),
    _profile("mayonnaise", "0.91", "mayo", reference="Mayonnaise, traditional"),
    _profile("jam", "1.333", "preserve", reference="Jam"),
    _profile("chocolate hazelnut spread", "1.26", "nutella", reference="Nutella"),
    _profile("tomato puree", "1.08", "tomato paste", reference="FDC household portion", source=USDA_FDC_SOURCE),
    _profile("short pasta", "0.39", "macaroni", "penne", "fusilli", reference="Pasta, short macaroni style, raw"),
    _profile("lentils", "0.89", "green lentils", "dry lentils", reference="Lentils, green, small, raw"),
    _profile("almonds", "0.46", reference="Almonds"),
    _profile("cashews", "0.50", reference="Cashews"),
    _profile("flaxseed", "0.70", "linseed", reference="Flaxseed"),
    _profile(
        "chia seeds", "0.72", "chia seed", source=HEALTH_CANADA_SOURCE,
        source_url=HEALTH_CANADA_CHIA_URL,
        reference="Canadian Nutrient File food 2511: 10.8 g per 15 ml",
    ),
    _profile(
        "coriander leaves", "0.06667", "coriander leaf", "cilantro",
        "fresh coriander", "fresh cilantro", source=USDA_FDC_SOURCE,
        reference="FDC 169997: 4 g per 1/4 cup",
    ),
    _profile(
        "dried coriander leaves", "0.12", "dried coriander leaf",
        "dried cilantro", source=USDA_FDC_SOURCE,
        reference="FDC 170921: 0.6 g per tsp and 1.8 g per tbsp",
    ),
    _profile(
        "coriander seeds", "0.35", "coriander seed", source=USDA_FDC_SOURCE,
        reference="FDC 170922 household tsp and tbsp portions",
    ),
    _profile("cinnamon", "0.56", "ground cinnamon", "cinnamon powder", reference="Cinnamon, powder"),
    _profile("garlic powder", "0.32", reference="Garlic, powder"),
)


_PUNCTUATION = re.compile(r"[^a-z0-9]+")
_ALIASES: dict[str, IngredientMeasurementProfile] = {}


def normalise_measurement_name(value: str) -> str:
    return " ".join(_PUNCTUATION.sub(" ", value.casefold()).split())


for _entry in INGREDIENT_MEASUREMENT_PROFILES:
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

SHOPPING_DISPLAY_UNITS = ("g", "ml", "tbsp", "tsp", "cup")


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
        if target in MASS_TO_G:
            return grams / MASS_TO_G[target]
        if target in VOLUME_TO_ML and density_g_per_ml:
            return (grams / density_g_per_ml) / VOLUME_TO_ML[target]
        return None
    if canonical in VOLUME_TO_ML:
        millilitres = Decimal(quantity) * VOLUME_TO_ML[canonical]
        if target in VOLUME_TO_ML:
            return millilitres / VOLUME_TO_ML[target]
        if target in MASS_TO_G and density_g_per_ml:
            return (millilitres * density_g_per_ml) / MASS_TO_G[target]
        return None
    return None


def normalise_shopping_measurement(
    quantity: Decimal,
    unit: str,
    density_g_per_ml: Decimal | None,
) -> tuple[Decimal, str]:
    """Normalize to stable mass/volume storage without choosing presentation."""

    canonical = canonical_quantity_unit(unit)
    dimension = measurement_dimension(canonical)
    if dimension is None:
        return Decimal(quantity), canonical
    target = "g" if dimension == "mass" or density_g_per_ml is not None else "ml"
    converted = convert_quantity_to_unit(
        Decimal(quantity), canonical, target, density_g_per_ml
    )
    return (converted if converted is not None else Decimal(quantity)), target


def available_display_units(
    storage_unit: str,
    density_g_per_ml: Decimal | None,
) -> tuple[str, ...]:
    canonical = canonical_quantity_unit(storage_unit)
    dimension = measurement_dimension(canonical)
    if dimension is None:
        return (canonical,)
    if density_g_per_ml is not None:
        return SHOPPING_DISPLAY_UNITS
    if dimension == "mass":
        return ("g",)
    return ("ml", "tbsp", "tsp", "cup")
