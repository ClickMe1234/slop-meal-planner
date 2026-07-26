from __future__ import annotations

from collections.abc import Mapping
import logging
import re
from threading import Lock
from time import monotonic

import httpx
from sqlalchemy.orm import Session

from ..data_import.models import DatasetProvenance, FoodDataBatch
from ..data_import.persistence import persist_food_batch
from ..data_import.providers.usda import UsdaFoodDataCentralProvider
from .ingredients import food_search_phrase


REQUIRED_NUTRIENTS = {"energy_kcal", "protein_g", "carbohydrate_g", "fat_g"}
_rate_limit_lock = Lock()
_rate_limited_until = 0.0
_API_KEY_PATTERN = re.compile(r"(?i)([?&]api_key=)[^&\s]+")


class _ApiKeyRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        def redact(value: object) -> object:
            return _API_KEY_PATTERN.sub(r"\1[REDACTED]", value) if isinstance(value, str) else value

        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True


logging.getLogger("httpx").addFilter(_ApiKeyRedactionFilter())


class FoodDataCentralError(RuntimeError):
    pass


class FoodDataCentralConfigurationError(FoodDataCentralError):
    pass


class FoodDataCentralRateLimited(FoodDataCentralError):
    pass


class FoodDataCentralUnavailable(FoodDataCentralError):
    pass


def normalise_food_query(query: str) -> str:
    return food_search_phrase(query) or " ".join(query.split())[:200]


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

    global _rate_limited_until
    cleaned = normalise_food_query(query)
    if len(cleaned) < 2:
        return 0
    if not api_key.strip():
        raise FoodDataCentralConfigurationError("A USDA FoodData Central API key has not been configured")
    with _rate_limit_lock:
        if monotonic() < _rate_limited_until:
            raise FoodDataCentralRateLimited("The USDA FoodData Central quota is temporarily exhausted")
    owns_client = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(8.0, connect=4.0))
    try:
        try:
            response = http.post(
                f"{UsdaFoodDataCentralProvider.api_base_url}/foods/search",
                params={"api_key": api_key},
                json={
                    "query": cleaned,
                    "pageSize": page_size,
                    "dataType": ["Foundation", "SR Legacy", "Survey (FNDDS)"],
                    "sortBy": "dataType.keyword",
                    "sortOrder": "asc",
                },
                headers={"User-Agent": "SlopMealPlanner/1.1.1"},
            )
            if response.status_code == 429:
                with _rate_limit_lock:
                    _rate_limited_until = monotonic() + 300
                raise FoodDataCentralRateLimited("The USDA FoodData Central quota is temporarily exhausted")
            response.raise_for_status()
            payload = response.json()
        except FoodDataCentralError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise FoodDataCentralUnavailable("USDA FoodData Central could not be reached") from exc
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
