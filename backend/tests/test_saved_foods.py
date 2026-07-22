from decimal import Decimal

from app.data_import.models import NormalizedFood, NutrientValue
from app.models import FoodNutrient, FoodRecord, Household
from app.routes import food_routes
from app.services.open_food_facts import SearchResult


NUTRIENTS = [
    {"code": "energy_kcal", "amount": 120, "unit": "kcal"},
    {"code": "protein_g", "amount": 8, "unit": "g"},
    {"code": "carbohydrate_g", "amount": 12, "unit": "g"},
    {"code": "fat_g", "amount": 4, "unit": "g"},
]


def test_packaged_food_search_normalizes_surrounding_whitespace(client, owner, monkeypatch):
    observed: dict[str, str] = {}

    def fake_search(query, **_kwargs):
        observed["query"] = query
        return SearchResult(foods=(), page=1, has_more=False)

    monkeypatch.setattr(food_routes, "search_products", fake_search)
    response = client.post(
        "/api/v1/food-lookups/search",
        json={"query": "  Greek   yogurt Milbona  ", "page": 1},
    )

    assert response.status_code == 200, response.text
    assert observed["query"] == "Greek yogurt Milbona"


def test_manual_food_can_feed_recipes_planning_and_pantry(client, owner):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    created = client.post(
        "/api/v1/saved-foods",
        headers=headers,
        json={
            "source_type": "manual",
            "display_name": "House yoghurt",
            "basis_amount": 100,
            "basis_unit": "g",
            "nutrients": NUTRIENTS,
        },
    )
    assert created.status_code == 201, created.text
    food = created.json()
    assert food["provider"] == "user"
    assert Decimal(food["nutrients"]["protein_g"]) == 8

    planned = client.patch(
        f"/api/v1/saved-foods/{food['id']}",
        headers=headers,
        json={
            "expected_version": food["version"],
            "display_name": "House yoghurt pot",
            "serving_amount": 150,
            "serving_unit": "g",
            "planner_enabled": True,
            "meal_types": ["breakfast", "snack"],
        },
    )
    assert planned.status_code == 200, planned.text
    planned_saved = planned.json()
    assert planned_saved["planner_enabled"] is True
    assert set(planned_saved["meal_types"]) == {"breakfast", "snack"}
    assert planned_saved["planner_recipe_id"]

    regular_recipes = client.get("/api/v1/recipes?page_size=100")
    assert all(item["source_type"] != "food" for item in regular_recipes.json()["items"])
    planner_recipes = client.get("/api/v1/recipes?page_size=100&include_food=true")
    planner_choice = next(
        item for item in planner_recipes.json()["items"] if item["source_type"] == "food"
    )
    assert planner_choice["planner_eligible"] is True
    assert planner_choice["calculated_nutrition"]["energy_kcal"] == 180

    pantry = client.post(
        "/api/v1/pantry-items",
        headers=headers,
        json={
            "display_name": planned_saved["display_name"],
            "food_record_id": planned_saved["food_record_id"],
            "quantity": 450,
            "unit": "g",
            "use_soon": True,
        },
    )
    assert pantry.status_code == 201, pantry.text
    assert pantry.json()["food_record_id"] == planned_saved["food_record_id"]
    assert pantry.json()["use_soon"] is True

    recipe = client.post(
        "/api/v1/recipes",
        headers=headers,
        json={
            "title": "Yoghurt bowl",
            "yield_servings": 1,
            "source_type": "custom",
            "meal_types": ["breakfast"],
            "ingredients": [
                {
                    "original_text": "200g house yoghurt",
                    "quantity": 200,
                    "unit": "g",
                    "quantity_grams": 200,
                    "food_record_id": planned_saved["food_record_id"],
                }
            ],
        },
    )
    assert recipe.status_code == 201, recipe.text
    assert recipe.json()["planner_eligible"] is True
    assert recipe.json()["calculated_nutrition"]["energy_kcal"] == 240


def test_open_food_facts_barcode_can_be_previewed_and_saved(client, owner, monkeypatch):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    food = NormalizedFood(
        provider="open_food_facts",
        provider_record_id="5000123456789",
        dataset_version="Open Food Facts product 1",
        name="Example beans",
        basis_amount=Decimal("100"),
        basis_unit="g",
        nutrients=tuple(
            NutrientValue(item["code"], Decimal(str(item["amount"])), item["unit"])
            for item in NUTRIENTS
        ),
        metadata={
            "brands": "Example",
            "source_url": "https://world.openfoodfacts.org/product/5000123456789",
            "attribution": "Product data from Open Food Facts (ODbL)",
            "image_url": "https://images.openfoodfacts.org/example-beans.jpg",
            "package_amount": "400",
            "package_unit": "g",
            "serving_amount": "200",
            "serving_unit": "g",
        },
    )
    monkeypatch.setattr(food_routes, "_lookup_barcode", lambda _: food)

    preview = client.get("/api/v1/food-lookups/barcode/5000123456789")
    assert preview.status_code == 200, preview.text
    assert Decimal(preview.json()["package_amount"]) == 400
    assert preview.json()["complete"] is True
    assert preview.json()["image_url"] == "https://images.openfoodfacts.org/example-beans.jpg"

    saved = client.post(
        "/api/v1/saved-foods",
        headers=headers,
        json={"source_type": "open_food_facts", "barcode": "5000123456789"},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["barcode"] == "5000123456789"
    assert Decimal(saved.json()["serving_amount"]) == 200
    assert saved.json()["attribution"] == "Product data from Open Food Facts (ODbL)"
    assert saved.json()["image_url"] == "https://images.openfoodfacts.org/example-beans.jpg"

    planned = client.patch(
        f"/api/v1/saved-foods/{saved.json()['id']}",
        headers=headers,
        json={
            "expected_version": saved.json()["version"],
            "display_name": "Example beans",
            "serving_amount": 200,
            "serving_unit": "g",
            "planner_enabled": True,
            "meal_types": ["lunch"],
        },
    )
    assert planned.status_code == 200, planned.text
    planner_recipes = client.get("/api/v1/recipes?page_size=100&include_food=true")
    planner_choice = next(
        item for item in planner_recipes.json()["items"] if item["source_type"] == "food"
    )
    assert planner_choice["image_url"] == "https://images.openfoodfacts.org/example-beans.jpg"


def test_zero_macro_values_are_complete(client, owner):
    response = client.post(
        "/api/v1/saved-foods",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={
            "source_type": "manual",
            "display_name": "Cooking oil",
            "nutrients": [
                {"code": "energy_kcal", "amount": 884, "unit": "kcal"},
                {"code": "protein_g", "amount": 0, "unit": "g"},
                {"code": "carbohydrate_g", "amount": 0, "unit": "g"},
                {"code": "fat_g", "amount": 100, "unit": "g"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["warnings"] == []


def test_private_food_records_cannot_cross_households(client, owner, session_factory):
    with session_factory() as db:
        other_household = Household(name="Other household")
        db.add(other_household)
        db.flush()
        private_food = FoodRecord(
            owner_household_id=other_household.id,
            provider="user",
            provider_record_id="other-private-food",
            dataset_version="Household manual entry",
            name="Secret other-household ingredient",
            basis_amount=100,
            basis_unit="g",
        )
        db.add(private_food)
        db.flush()
        for item in NUTRIENTS:
            db.add(FoodNutrient(food_record_id=private_food.id, **item))
        db.commit()
        private_food_id = private_food.id

    search = client.get("/api/v1/foods")
    assert search.status_code == 200
    assert private_food_id not in {item["id"] for item in search.json()["items"]}

    headers = {"X-CSRF-Token": owner["csrf_token"]}
    pantry = client.post(
        "/api/v1/pantry-items",
        headers=headers,
        json={
            "display_name": "Not ours",
            "food_record_id": private_food_id,
            "quantity": 100,
            "unit": "g",
        },
    )
    assert pantry.status_code == 404

    recipe = client.post(
        "/api/v1/recipes",
        headers=headers,
        json={
            "title": "Not ours",
            "yield_servings": 1,
            "ingredients": [
                {
                    "original_text": "100g private ingredient",
                    "quantity": 100,
                    "unit": "g",
                    "quantity_grams": 100,
                    "food_record_id": private_food_id,
                }
            ],
        },
    )
    assert recipe.status_code == 404


def test_general_food_search_matches_words_in_any_order(client, owner, session_factory):
    with session_factory() as db:
        food = FoodRecord(
            provider="usda_fdc",
            provider_record_id="greek-yogurt-test",
            dataset_version="test",
            name="Yogurt, Greek, plain",
            basis_amount=100,
            basis_unit="g",
        )
        db.add(food)
        db.flush()
        for item in NUTRIENTS:
            db.add(FoodNutrient(food_record_id=food.id, **item))
        db.commit()

    response = client.get("/api/v1/foods?q=greek%20yogurt")

    assert response.status_code == 200, response.text
    assert [item["name"] for item in response.json()["items"]] == ["Yogurt, Greek, plain"]
