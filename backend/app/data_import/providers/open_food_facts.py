from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from ..errors import ProviderResponseError
from ..models import NormalizedFood, NutrientValue
from .base import FoodDataProvider


class OpenFoodFactsProvider(FoodDataProvider):
    key = "open_food_facts"
    api_base_url = "https://world.openfoodfacts.org/api/v2"

    def __init__(self, *, dataset_version: str = "Open Food Facts live API") -> None:
        self.dataset_version = dataset_version

    @staticmethod
    def product_url(barcode: str) -> str:
        cleaned = "".join(character for character in barcode if character.isdigit())
        if not cleaned:
            raise ValueError("A numeric barcode is required")
        return f"https://world.openfoodfacts.org/api/v2/product/{cleaned}.json"

    def normalise_record(self, payload: Mapping[str, object]) -> NormalizedFood:
        product = payload.get("product") if isinstance(payload.get("product"), Mapping) else payload
        barcode = product.get("code") or payload.get("code")
        name = product.get("product_name") or product.get("product_name_en")
        if barcode is None or not isinstance(name, str) or not name.strip():
            raise ProviderResponseError("The Open Food Facts response did not contain a barcode and product name")
        nutriments = product.get("nutriments")
        if not isinstance(nutriments, Mapping):
            nutriments = {}
        mapping = {
            "energy-kcal_100g": ("energy_kcal", "kcal"),
            "proteins_100g": ("protein_g", "g"),
            "carbohydrates_100g": ("carbohydrate_g", "g"),
            "fat_100g": ("fat_g", "g"),
            "fiber_100g": ("fibre_g", "g"),
        }
        values: dict[str, NutrientValue] = {}
        for source_key, (code, unit) in mapping.items():
            raw = nutriments.get(source_key)
            try:
                amount = Decimal(str(raw)) if raw is not None else None
            except InvalidOperation:
                amount = None
            if raw is not None:
                values[code] = NutrientValue(code, amount, unit, None if amount is not None else "unparsed")
        if "energy_kcal" not in values and nutriments.get("energy_100g") is not None:
            try:
                energy_kj = Decimal(str(nutriments["energy_100g"]))
            except InvalidOperation:
                energy_kj = None
            values["energy_kcal"] = NutrientValue(
                "energy_kcal",
                energy_kj / Decimal("4.184") if energy_kj is not None else None,
                "kcal",
                "converted_from_kj",
            )
        metadata = {
            key: product[key]
            for key in ("brands", "quantity", "serving_size", "last_modified_t")
            if isinstance(product.get(key), (str, int, float, bool))
        }
        return NormalizedFood(
            provider=self.key,
            provider_record_id=str(barcode),
            dataset_version=self.dataset_version,
            name=name.strip(),
            nutrients=tuple(values.values()),
            metadata=metadata,
        )
