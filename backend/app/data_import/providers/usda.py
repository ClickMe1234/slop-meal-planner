from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from ..errors import ProviderConfigurationError, ProviderResponseError
from ..models import NormalizedFood, NutrientValue
from .base import FoodDataProvider


USDA_NUTRIENT_CODES = {
    1008: ("energy_kcal", "kcal"),
    1062: ("energy_kj", "kJ"),
    1003: ("protein_g", "g"),
    1004: ("fat_g", "g"),
    1005: ("carbohydrate_g", "g"),
    1079: ("fibre_g", "g"),
}


class UsdaFoodDataCentralProvider(FoodDataProvider):
    key = "usda_fdc"
    api_base_url = "https://api.nal.usda.gov/fdc/v1"

    def __init__(self, api_key: str | None = None, *, dataset_version: str = "FoodData Central live API") -> None:
        self.api_key = api_key
        self.dataset_version = dataset_version

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ProviderConfigurationError("A USDA FoodData Central API key has not been configured")
        return self.api_key

    def normalise_record(self, payload: Mapping[str, object]) -> NormalizedFood:
        record_id = payload.get("fdcId")
        name = payload.get("description")
        if record_id is None or not isinstance(name, str) or not name.strip():
            raise ProviderResponseError("The USDA response did not contain fdcId and description")
        values: dict[str, NutrientValue] = {}
        rows = payload.get("foodNutrients")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                nutrient = row.get("nutrient") if isinstance(row.get("nutrient"), Mapping) else row
                nutrient_id = nutrient.get("id") or row.get("nutrientId")
                try:
                    mapping = USDA_NUTRIENT_CODES.get(int(nutrient_id))
                except (TypeError, ValueError):
                    mapping = None
                if mapping is None:
                    continue
                raw_amount = row.get("amount") if "amount" in row else row.get("value")
                try:
                    amount = Decimal(str(raw_amount))
                except (InvalidOperation, TypeError):
                    amount = None
                code, unit = mapping
                values[code] = NutrientValue(code, amount, unit)
        if "energy_kcal" not in values and (energy_kj := values.get("energy_kj")):
            values["energy_kcal"] = NutrientValue(
                "energy_kcal",
                energy_kj.amount / Decimal("4.184") if energy_kj.amount is not None else None,
                "kcal",
                "converted_from_kj",
            )
        values.pop("energy_kj", None)
        metadata = {
            key: payload[key]
            for key in ("dataType", "publicationDate", "brandOwner", "gtinUpc")
            if isinstance(payload.get(key), (str, int, float, bool))
        }
        return NormalizedFood(
            provider=self.key,
            provider_record_id=str(record_id),
            dataset_version=self.dataset_version,
            name=name.strip(),
            nutrients=tuple(values.values()),
            metadata=metadata,
        )
