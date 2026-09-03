import httpx
import pytest

from app.services import food_search, open_food_facts


def test_open_food_facts_retries_transient_search_and_caches_success(monkeypatch):
    calls = 0
    open_food_facts._search_cache.clear()
    open_food_facts._search_requests.clear()
    monkeypatch.setattr(open_food_facts, "sleep", lambda _seconds: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={
                "page_count": 1,
                "products": [
                    {
                        "code": "5000123456789",
                        "product_name": "Reliable beans",
                        "nutriments": {
                            "energy-kcal_100g": 81,
                            "proteins_100g": 4.7,
                            "carbohydrates_100g": 12.5,
                            "fat_100g": 0.4,
                        },
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = open_food_facts.search_products(
            "resilient beans",
            page=1,
            user_agent="SlopMealPlanner/test",
            client=client,
        )
        second = open_food_facts.search_products(
            "resilient beans",
            page=1,
            user_agent="SlopMealPlanner/test",
            client=client,
        )

    assert calls == 2
    assert first.foods[0].name == "Reliable beans"
    assert second == first


def test_open_food_facts_barcode_accepts_a_v3_product_response_without_status():
    open_food_facts._product_requests.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/product/5000123456789"
        return httpx.Response(
            200,
            request=request,
            json={
                "code": "5000123456789",
                "errors": [],
                "product": {
                    "code": "5000123456789",
                    "product_name": "Reliable beans",
                    "brands": "Example Foods",
                    "nutriments": {
                        "energy-kcal_100g": 81,
                        "proteins_100g": 4.7,
                        "carbohydrates_100g": 12.5,
                        "fat_100g": 0.4,
                    },
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        food = open_food_facts.lookup_product(
            "5000123456789",
            user_agent="SlopMealPlanner/test",
            client=client,
        )

    assert food.name == "Reliable beans"
    assert food.metadata["brands"] == "Example Foods"


def test_food_data_central_rate_limit_enters_short_cooldown(monkeypatch, db):
    calls = 0
    monkeypatch.setattr(food_search, "_rate_limited_until", 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, request=request, json={"error": {"code": "OVER_RATE_LIMIT"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(food_search.FoodDataCentralRateLimited):
            food_search.fetch_and_cache_usda_foods(
                db,
                "greek yogurt",
                api_key="DEMO_KEY",
                client=client,
            )
        with pytest.raises(food_search.FoodDataCentralRateLimited):
            food_search.fetch_and_cache_usda_foods(
                db,
                "plain yogurt",
                api_key="DEMO_KEY",
                client=client,
            )

    assert calls == 1


def test_food_data_central_requires_a_configured_key(db):
    with pytest.raises(food_search.FoodDataCentralConfigurationError):
        food_search.fetch_and_cache_usda_foods(db, "lentils", api_key="")
