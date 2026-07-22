from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import re

from ..errors import ProviderResponseError
from ..models import NormalizedFood, NutrientValue
from .base import FoodDataProvider


class OpenFoodFactsProvider(FoodDataProvider):
    key = "open_food_facts"
    api_base_url = "https://world.openfoodfacts.org/api/v3"

    def __init__(self, *, dataset_version: str = "Open Food Facts live API") -> None:
        self.dataset_version = dataset_version

    @staticmethod
    def product_url(barcode: str) -> str:
        cleaned = "".join(character for character in barcode if character.isdigit())
        if not cleaned:
            raise ValueError("A numeric barcode is required")
        return f"https://world.openfoodfacts.org/api/v3/product/{cleaned}"

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _unit(value: object) -> str | None:
        raw = str(value or "").strip().casefold()
        if raw in {"g", "gram", "grams", "kg"}:
            return "g"
        if raw in {"ml", "millilitre", "millilitres", "cl", "l", "litre", "litres"}:
            return "ml"
        return None

    @classmethod
    def _normalised_quantity(cls, value: object, source_unit: object) -> tuple[Decimal | None, str | None]:
        amount = cls._decimal(value)
        raw_unit = str(source_unit or "").strip().casefold()
        unit = cls._unit(raw_unit)
        if amount is None or unit is None:
            return None, None
        if raw_unit == "kg":
            amount *= Decimal("1000")
        elif raw_unit == "l":
            amount *= Decimal("1000")
        elif raw_unit == "cl":
            amount *= Decimal("10")
        return amount, unit

    @classmethod
    def _serving(cls, product: Mapping[str, object], basis_unit: str) -> tuple[Decimal | None, str | None]:
        text = str(product.get("serving_size") or "").casefold()
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|l)\b", text)
        if match:
            return cls._normalised_quantity(match.group(1).replace(",", "."), match.group(2))
        amount = cls._decimal(product.get("serving_quantity"))
        return (amount, basis_unit) if amount is not None else (None, None)

    def normalise_record(self, payload: Mapping[str, object]) -> NormalizedFood:
        product = payload.get("product") if isinstance(payload.get("product"), Mapping) else payload
        barcode = product.get("code") or payload.get("code")
        name = product.get("product_name_en") or product.get("product_name")
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
            amount = self._decimal(raw)
            if raw is not None:
                values[code] = NutrientValue(code, amount, unit, None if amount is not None else "unparsed")
        if "energy_kcal" not in values and nutriments.get("energy_100g") is not None:
            energy_kj = self._decimal(nutriments["energy_100g"])
            values["energy_kcal"] = NutrientValue(
                "energy_kcal",
                energy_kj / Decimal("4.184") if energy_kj is not None else None,
                "kcal",
                "converted_from_kj",
            )
        package_amount, package_unit = self._normalised_quantity(
            product.get("product_quantity"), product.get("product_quantity_unit")
        )
        basis_unit = package_unit or "g"
        serving_amount, serving_unit = self._serving(product, basis_unit)
        metadata = {
            key: product[key]
            for key in ("brands", "quantity", "serving_size", "last_modified_t")
            if isinstance(product.get(key), (str, int, float, bool))
        }
        metadata.update(
            {
                "barcode": str(barcode),
                "source_url": f"https://world.openfoodfacts.org/product/{barcode}",
                "attribution": "Product data from Open Food Facts (ODbL)",
                "package_amount": str(package_amount) if package_amount is not None else None,
                "package_unit": package_unit,
                "serving_amount": str(serving_amount) if serving_amount is not None else None,
                "serving_unit": serving_unit,
                "basis_inferred": package_unit is None,
            }
        )
        return NormalizedFood(
            provider=self.key,
            provider_record_id=str(barcode),
            dataset_version=self.dataset_version,
            name=name.strip(),
            basis_unit=basis_unit,
            nutrients=tuple(values.values()),
            metadata=metadata,
        )
