from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from threading import Lock
from time import monotonic, sleep

import httpx

from ..data_import.models import NormalizedFood
from ..data_import.providers.open_food_facts import OpenFoodFactsProvider


FIELDS = ",".join(
    (
        "code",
        "product_name",
        "product_name_en",
        "brands",
        "product_quantity",
        "product_quantity_unit",
        "quantity",
        "serving_size",
        "serving_quantity",
        "nutriments",
        "last_modified_t",
    )
)
REQUIRED_NUTRIENTS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g")


class OpenFoodFactsError(RuntimeError):
    pass


class OpenFoodFactsNotFound(OpenFoodFactsError):
    pass


class OpenFoodFactsUnavailable(OpenFoodFactsError):
    pass


class OpenFoodFactsRateLimited(OpenFoodFactsUnavailable):
    pass


@dataclass(frozen=True, slots=True)
class SearchResult:
    foods: tuple[NormalizedFood, ...]
    page: int
    has_more: bool


_product_requests: deque[float] = deque()
_search_requests: deque[float] = deque()
_rate_lock = Lock()
_search_cache: OrderedDict[tuple[str, int, int], tuple[float, SearchResult]] = OrderedDict()
_search_cache_lock = Lock()
_SEARCH_CACHE_SECONDS = 300
_SEARCH_CACHE_SIZE = 64


def _claim_rate_slot(bucket: deque[float], limit: int) -> None:
    now = monotonic()
    with _rate_lock:
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= limit:
            raise OpenFoodFactsRateLimited("Open Food Facts is temporarily rate limited")
        bucket.append(now)


def clean_barcode(value: str) -> str:
    cleaned = "".join(character for character in value if character.isdigit())
    if not 4 <= len(cleaned) <= 24:
        raise ValueError("Enter a barcode containing 4 to 24 digits")
    return cleaned


def _client(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 4.0)),
        follow_redirects=True,
    )


def _request_json(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, object],
    user_agent: str,
    rate_bucket: deque[float],
    rate_limit: int,
    max_attempts: int = 3,
) -> Mapping[str, object]:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        _claim_rate_slot(rate_bucket, rate_limit)
        try:
            response = client.get(
                url,
                params=params,
                headers={"User-Agent": user_agent, "Accept": "application/json"},
            )
            if response.status_code == 429:
                raise OpenFoodFactsRateLimited("Open Food Facts asked Slop to slow down")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise ValueError("Open Food Facts returned a non-object response")
            return payload
        except OpenFoodFactsRateLimited:
            raise
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code not in {502, 503, 504}:
                raise OpenFoodFactsUnavailable("Open Food Facts could not be reached") from exc
        except (httpx.TransportError, ValueError) as exc:
            last_error = exc
        if attempt + 1 < max_attempts:
            sleep(0.15 * (2**attempt))
    raise OpenFoodFactsUnavailable("Open Food Facts is temporarily unavailable") from last_error


def _cached_search(key: tuple[str, int, int]) -> SearchResult | None:
    now = monotonic()
    with _search_cache_lock:
        cached = _search_cache.get(key)
        if cached is None:
            return None
        created_at, result = cached
        if now - created_at >= _SEARCH_CACHE_SECONDS:
            del _search_cache[key]
            return None
        _search_cache.move_to_end(key)
        return result


def _cache_search(key: tuple[str, int, int], result: SearchResult) -> None:
    with _search_cache_lock:
        _search_cache[key] = (monotonic(), result)
        _search_cache.move_to_end(key)
        while len(_search_cache) > _SEARCH_CACHE_SIZE:
            _search_cache.popitem(last=False)


def lookup_product(
    barcode: str,
    *,
    user_agent: str,
    timeout_seconds: float = 8.0,
    client: httpx.Client | None = None,
) -> NormalizedFood:
    code = clean_barcode(barcode)
    owns_client = client is None
    http = client or _client(timeout_seconds)
    try:
        payload = _request_json(
            http,
            OpenFoodFactsProvider.product_url(code),
            params={"fields": FIELDS},
            user_agent=user_agent,
            rate_bucket=_product_requests,
            rate_limit=15,
        )
    finally:
        if owns_client:
            http.close()
    if payload.get("status") not in {"success", 1, "1"} or not isinstance(payload.get("product"), Mapping):
        raise OpenFoodFactsNotFound("No Open Food Facts product matched that barcode")
    product = payload["product"]
    version = f"Open Food Facts product {product.get('last_modified_t') or 'live'}"
    return OpenFoodFactsProvider(dataset_version=version).normalise_record(payload)


def search_products(
    query: str,
    *,
    page: int,
    user_agent: str,
    timeout_seconds: float = 8.0,
    page_size: int = 12,
    client: httpx.Client | None = None,
) -> SearchResult:
    cleaned = " ".join(query.split())[:200]
    if len(cleaned) < 2:
        raise ValueError("Enter at least two characters")
    cache_key = (cleaned.casefold(), page, page_size)
    cached = _cached_search(cache_key)
    if cached is not None:
        return cached
    owns_client = client is None
    http = client or _client(timeout_seconds)
    try:
        payload = _request_json(
            http,
            "https://world.openfoodfacts.org/cgi/search.pl",
            params={
                "search_terms": cleaned,
                "search_simple": 1,
                "action": "process",
                "json": 1,
                "page": page,
                "page_size": page_size,
                "fields": FIELDS,
            },
            user_agent=user_agent,
            rate_bucket=_search_requests,
            rate_limit=10,
        )
    finally:
        if owns_client:
            http.close()

    foods: list[NormalizedFood] = []
    for product in payload.get("products", []):
        if not isinstance(product, Mapping):
            continue
        try:
            version = f"Open Food Facts product {product.get('last_modified_t') or 'live'}"
            foods.append(OpenFoodFactsProvider(dataset_version=version).normalise_record(product))
        except Exception:
            continue
    page_count = int(payload.get("page_count") or len(foods))
    result = SearchResult(tuple(foods), page, page_count >= page_size)
    _cache_search(cache_key, result)
    return result


def nutrient_map(food: NormalizedFood) -> dict[str, Decimal | None]:
    values = {item.code: item.amount for item in food.nutrients}
    return {code: values.get(code) for code in REQUIRED_NUTRIENTS}
