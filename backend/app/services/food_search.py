from __future__ import annotations

from collections.abc import Mapping

import httpx
from sqlalchemy.orm import Session

from ..data_import.models import DatasetProvenance, FoodDataBatch
from ..data_import.persistence import persist_food_batch
from ..data_import.providers.usda import UsdaFoodDataCentralProvider


REQUIRED_NUTRIENTS = {"energy_kcal", "protein_g", "carbohydrate_g", "fat_g"}


def fetch_and_cache_usda_foods(
    db: Session,
    query: str,
    *,
    api_key: str,
    page_size: int = 12,
    client: httpx.Client | None = None,
) -> int:
    """Fetch real generic-food records from FoodData Central and cache them.

    The UI searches PostgreSQL first.  This function is called only when the
    local catalogue has too few matches, so subsequent searches and nutrition
    calculations use the durable, versioned records in our own database.
    """

    cleaned = " ".join(query.split())[:200]
    if len(cleaned) < 2:
        return 0
    owns_client = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(8.0, connect=4.0))
    try:
        response = http.post(
            f"{UsdaFoodDataCentralProvider.api_base_url}/foods/search",
            params={"api_key": api_key},
            json={
                "query": cleaned,
                "pageSize": page_size,
                "dataType": ["Foundation", "SR Legacy"],
                "sortBy": "dataType.keyword",
                "sortOrder": "asc",
            },
            headers={"User-Agent": "Savour meal planner/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            http.close()

    rows = payload.get("foods", []) if isinstance(payload, Mapping) else []
    provider = UsdaFoodDataCentralProvider(
        api_key=api_key,
        dataset_version="FoodData Central live API",
    )
    foods = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            food = provider.normalise_record(row)
        except Exception:
            continue
        nutrient_values = {item.code: item.amount for item in food.nutrients}
        if not REQUIRED_NUTRIENTS.issubset(nutrient_values):
            continue
        if any(nutrient_values[code] is None for code in REQUIRED_NUTRIENTS):
            continue
        foods.append(food)

    if not foods:
        return 0
    batch = FoodDataBatch(
        provenance=DatasetProvenance(
            provider=provider.key,
            dataset_version=provider.dataset_version,
            source_uri=f"{provider.api_base_url}/foods/search?query={cleaned}",
            license_name="USDA FoodData Central public-domain data",
        ),
        foods=tuple(foods),
    )
    result = persist_food_batch(db, batch)
    db.commit()
    return result.created + result.updated
