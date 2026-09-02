from decimal import Decimal

from sqlalchemy import select

from app.models import Household, MealBatch, Recipe, RecipeVersion


def test_recipe_serving_constraints_are_saved_together(client, owner):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    response = client.post(
        "/api/v1/recipes",
        headers=headers,
        json={
            "title": "Whole egg omelette",
            "source_type": "url",
            "source_url": "https://example.com/whole-egg-omelette",
            "yield_servings": 2,
            "minimum_servings": 1,
            "serving_increment": 0.5,
            "ingredients": [
                {
                    "original_text": "2 eggs",
                    "quantity": 2,
                    "unit": "item",
                    "food_phrase": "eggs",
                }
            ],
        },
    )

    assert response.status_code == 201, response.text
    assert Decimal(response.json()["minimum_servings"]) == Decimal("1")
    assert Decimal(response.json()["serving_increment"]) == Decimal("0.5")

    created = response.json()
    ingredient = created["ingredients"][0]
    reviewed = client.put(
        f"/api/v1/recipes/{created['id']}/review",
        headers=headers,
        json={
            "expected_version": created["version"],
            "title": created["title"],
            "yield_servings": 2,
            "ingredients": [
                {
                    "lineage_id": ingredient["lineage_id"],
                    "original_text": ingredient["original_text"],
                    "quantity": 2,
                    "unit": "item",
                    "food_phrase": "eggs",
                }
            ],
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert Decimal(reviewed.json()["minimum_servings"]) == Decimal("1")
    assert Decimal(reviewed.json()["serving_increment"]) == Decimal("0.5")

    one_sided_clear = client.put(
        f"/api/v1/recipes/{created['id']}/review",
        headers=headers,
        json={
            "expected_version": reviewed.json()["version"],
            "title": created["title"],
            "yield_servings": 2,
            "minimum_servings": None,
            "ingredients": [
                {
                    "lineage_id": ingredient["lineage_id"],
                    "original_text": ingredient["original_text"],
                    "quantity": 2,
                    "unit": "item",
                    "food_phrase": "eggs",
                }
            ],
        },
    )
    assert one_sided_clear.status_code == 422
    assert "must be supplied together" in one_sided_clear.text

    incomplete = client.post(
        "/api/v1/recipes",
        headers=headers,
        json={
            "title": "Invalid constraints",
            "yield_servings": 2,
            "minimum_servings": 1,
            "ingredients": [],
        },
    )
    assert incomplete.status_code == 422
    assert "must be supplied together" in incomplete.text


def test_existing_import_drafts_are_enriched_with_detected_units(client, owner):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    recipe = client.post(
        "/api/v1/recipes",
        headers=headers,
        json={
            "title": "Imported chickpeas",
            "source_type": "url",
            "source_url": "https://www.bbcgoodfood.com/recipes/chickpeas",
            "yield_servings": 4,
            "ingredients": [
                {
                    "original_text": "2 x 400g cans chickpeas, drained",
                    "food_phrase": "2 x 400g cans chickpeas, drained",
                    "needs_review": True,
                }
            ],
        },
    )
    assert recipe.status_code == 201, recipe.text

    ingredient = client.get(f"/api/v1/recipes/{recipe.json()['id']}").json()["ingredients"][0]
    assert ingredient["quantity"] == "2"
    assert ingredient["unit"] == "can"
    assert ingredient["quantity_grams"] == "800"
    assert ingredient["food_phrase"] == "chickpeas"


def test_recipe_review_saves_manual_import_nutrition_for_planning(client, owner, session_factory):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    created = client.post(
        "/api/v1/recipes",
        headers=headers,
        json={
            "title": "Nutrition review dinner",
            "source_type": "url",
            "source_url": "https://recipes.example.org/nutrition-review",
            "yield_servings": 4,
            "ingredients": [{
                "original_text": "100 g spinach",
                "quantity": 100,
                "unit": "g",
                "quantity_grams": 100,
                "food_phrase": "spinach",
            }],
        },
    )
    assert created.status_code == 201, created.text
    current = created.json()
    assert current["publisher_nutrition"] is None
    ingredient = current["ingredients"][0]

    reviewed = client.put(
        f"/api/v1/recipes/{current['id']}/review",
        headers=headers,
        json={
            "expected_version": current["version"],
            "title": current["title"],
            "yield_servings": current["yield_servings"],
            "meal_types": ["dinner"],
            "publisher_nutrition": {
                "energy_kcal": 475,
                "protein_g": 32,
                "carbohydrate_g": 41,
                "fat_g": 17,
                "fibre_g": 7,
            },
            "ingredients": [{
                "lineage_id": ingredient["lineage_id"],
                "original_text": ingredient["original_text"],
                "quantity": ingredient["quantity"],
                "unit": ingredient["unit"],
                "quantity_grams": ingredient["quantity_grams"],
                "food_phrase": ingredient["food_phrase"],
                "included": True,
                "optional": False,
                "needs_review": False,
                "shopping_excluded": False,
            }],
        },
    )

    assert reviewed.status_code == 200, reviewed.text
    saved = reviewed.json()
    assert saved["publisher_nutrition"] == {
        "basis": "per serving",
        "energy_kcal": 475.0,
        "protein_g": 32.0,
        "carbohydrate_g": 41.0,
        "fat_g": 17.0,
        "fibre_g": 7.0,
    }
    assert saved["planner_eligible"] is True
    assert saved["nutrition_method"] == "publisher"

    with session_factory() as db:
        version = db.scalar(
            select(RecipeVersion)
            .where(RecipeVersion.recipe_id == current["id"])
            .order_by(RecipeVersion.version_number.desc())
        )
        assert version.publisher_nutrition["energy_kcal"] == 475.0


def test_url_recipe_review_preserves_existing_publisher_nutrition_when_payload_is_blank(
    client, owner
):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    created = client.post(
        "/api/v1/recipes",
        headers=headers,
        json={
            "title": "Publisher nutrition stays put",
            "source_type": "url",
            "source_url": "https://www.bbcgoodfood.com/recipes/publisher-nutrition-stays-put",
            "yield_servings": 4,
            "meal_types": ["dinner"],
            "publisher_nutrition": {
                "basis": "per serving",
                "energy_kcal": 412,
                "protein_g": 18,
                "carbohydrate_g": 50,
                "fat_g": 10,
            },
            "ingredients": [{
                "original_text": "100 g spinach",
                "quantity": 100,
                "unit": "g",
                "quantity_grams": 100,
                "food_phrase": "spinach",
            }],
        },
    )
    assert created.status_code == 201, created.text
    current = created.json()
    ingredient = current["ingredients"][0]

    reviewed = client.put(
        f"/api/v1/recipes/{current['id']}/review",
        headers=headers,
        json={
            "expected_version": current["version"],
            "title": current["title"],
            "yield_servings": current["yield_servings"],
            "meal_types": ["dinner"],
            # A stale pre-editor client could send this after treating an old
            # ingredient calculation as authoritative. It must not erase the
            # publisher snapshot for a URL import.
            "publisher_nutrition": None,
            "ingredients": [{
                "lineage_id": ingredient["lineage_id"],
                "original_text": ingredient["original_text"],
                "quantity": ingredient["quantity"],
                "unit": ingredient["unit"],
                "quantity_grams": ingredient["quantity_grams"],
                "food_phrase": ingredient["food_phrase"],
                "included": True,
                "optional": False,
                "needs_review": False,
                "shopping_excluded": False,
            }],
        },
    )

    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["publisher_nutrition"]["energy_kcal"] == 412.0
    assert reviewed.json()["nutrition_method"] == "publisher"
    assert reviewed.json()["planner_eligible"] is True


def test_existing_publisher_import_is_derived_as_planner_ready(client, owner, session_factory):
    with session_factory() as db:
        household = db.scalar(select(Household))
        recipe = Recipe(
            household_id=household.id,
            title="Existing publisher recipe",
            eligibility="needs_review",
            source_type="url",
            source_url="https://www.bbcgoodfood.com/recipes/existing",
            publisher="Good Food",
        )
        db.add(recipe)
        db.flush()
        db.add(RecipeVersion(
            recipe_id=recipe.id,
            version_number=1,
            title=recipe.title,
            yield_servings=4,
            publisher_nutrition={
                "basis": "per serving",
                "energy_kcal": 400,
                "protein_g": 20,
                "carbohydrate_g": 50,
                "fat_g": 10,
            },
        ))
        db.commit()
        recipe_id = recipe.id

    listed = next(item for item in client.get("/api/v1/recipes").json()["items"] if item["id"] == recipe_id)
    assert listed["eligibility"] == "planner_ready"
    assert listed["nutrition_method"] == "publisher"
    assert listed["calculated_nutrition"]["energy_kcal"] == 400


def test_household_recipe_plan_pantry_and_shopping_loop(client, owner, session_factory):
    csrf = owner["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    target = client.put(
        f"/api/v1/household-members/{member_id}/target",
        headers=headers,
        json={
            "mode": "calorie",
            "calorie_target": 500,
            "tolerance_percent": 5,
            "allocations": [{"meal_type": "dinner", "percentage": 100}],
        },
    )
    assert target.status_code == 200, target.text

    food = client.post(
        "/api/v1/foods",
        headers=headers,
        json={
            "provider": "test",
            "provider_record_id": "rice-1",
            "dataset_version": "fixture-1",
            "name": "Cooked rice",
            "basis_amount": 100,
            "basis_unit": "g",
            "nutrients": [
                {"code": "energy_kcal", "amount": 500, "unit": "kcal"},
                {"code": "protein_g", "amount": 10, "unit": "g"},
                {"code": "carbohydrate_g", "amount": 100, "unit": "g"},
                {"code": "fat_g", "amount": 5, "unit": "g"},
            ],
        },
    )
    assert food.status_code == 201, food.text
    food_id = food.json()["id"]

    recipe = client.post(
        "/api/v1/recipes",
        headers=headers,
        json={
            "title": "Rice bowl",
            "yield_servings": 1,
            "source_type": "url",
            "source_url": "https://www.bbcgoodfood.com/recipes/rice-bowl",
            "publisher": "Good Food",
            "meal_types": ["dinner"],
            "publisher_nutrition": {
                "basis": "per serving",
                "energy_kcal": 500,
                "protein_g": 10,
                "carbohydrate_g": 100,
                "fat_g": 5,
            },
            "ingredients": [
                {
                    "original_text": "100 g cooked rice",
                    "quantity_grams": 100,
                    "unit": "g",
                    "food_phrase": "Cooked rice",
                    "food_record_id": food_id,
                }
            ],
        },
    )
    assert recipe.status_code == 201, recipe.text
    recipe_id = recipe.json()["id"]
    calculation = client.post(
        f"/api/v1/recipes/{recipe_id}/calculate", headers=headers
    )
    assert calculation.status_code == 200, calculation.text
    assert calculation.json()["per_serving_values"]["energy_kcal"] == 500
    listed_recipe = client.get("/api/v1/recipes").json()["items"][0]
    assert listed_recipe["yield_servings"] == "1.00"
    assert listed_recipe["nutrition_method"] == "publisher"
    assert listed_recipe["calculated_nutrition"]["energy_kcal"] == 500

    generated = client.post(
        "/api/v1/meal-plans/generate",
        headers=headers,
        json={
            "name": "Dinner",
            "recipe_ids": [recipe_id],
            "slots": [
                {
                    "meal_date": "2026-07-20",
                    "meal_type": "dinner",
                    "participant_member_ids": [member_id],
                }
            ],
        },
    )
    assert generated.status_code == 201, generated.text
    plan_id = generated.json()["id"]
    assert client.post(f"/api/v1/meal-plans/{plan_id}/accept", headers=headers).status_code == 200

    shopping = client.post(
        "/api/v1/shopping-lists/build",
        headers=headers,
        json={"meal_plan_id": plan_id, "name": "Dinner shopping"},
    )
    assert shopping.status_code == 201, shopping.text
    shopping_data = shopping.json()
    item = shopping_data["items"][0]
    assert item["exact_quantity"] == "100"
    assert item["exact_quantity_display"] == "100 g"
    assert item["available_units"] == ["g", "ml", "tbsp", "tsp", "cup"]
    assert len(item["quantity_options"]) == 5
    converted = client.patch(
        f"/api/v1/shopping-lists/{shopping_data['id']}/items/{item['id']}",
        headers=headers,
        json={"expected_version": item["version"], "display_unit": "cup"},
    )
    assert converted.status_code == 200, converted.text
    item = converted.json()
    assert item["unit"] == "cup"
    assert item["purchase_quantity_display"].endswith(" cup")
    checked = client.patch(
        f"/api/v1/shopping-lists/{shopping_data['id']}/items/{item['id']}",
        headers=headers,
        json={"expected_version": item["version"], "checked": True},
    )
    assert checked.status_code == 200, checked.text

    purchased = client.post(
        f"/api/v1/shopping-lists/{shopping_data['id']}/add-purchased-to-pantry",
        headers=headers,
    )
    assert purchased.status_code == 200, purchased.text
    assert purchased.json()[0]["reserved_quantity"] == "100"
    assert purchased.json()[0]["reserved_quantity_display"] == "100 g"
    assert purchased.json()[0]["usable_quantity"] == "0"

    plan = client.get(f"/api/v1/meal-plans/{plan_id}").json()
    batch_id = plan["occurrences"][0]["batch_id"]
    cooked = client.post(
        f"/api/v1/meal-plans/{plan_id}/batches/{batch_id}/cooked", headers=headers
    )
    assert cooked.status_code == 204
    pantry = client.get("/api/v1/pantry-items").json()[0]
    assert pantry["on_hand_quantity"] == "0"
    assert pantry["on_hand_quantity_display"] == "0 g"
    assert Decimal(pantry["reserved_quantity"]) == 0

    with session_factory() as db:
        db.get(MealBatch, batch_id).servings = Decimal("4")
        db.commit()
    weighed = client.patch(
        f"/api/v1/meal-plans/{plan_id}/batches/{batch_id}/cooked-weight",
        headers=headers,
        json={"cooked_weight_grams": 1003},
    )
    assert weighed.status_code == 204, weighed.text
    occurrence = client.get(f"/api/v1/meal-plans/{plan_id}").json()["occurrences"][0]
    assert Decimal(str(occurrence["cooked_weight_grams"])) == Decimal("1003")
    assert occurrence["serving_weight_grams"] == 251

    edited_weight = client.patch(
        f"/api/v1/meal-plans/{plan_id}/batches/{batch_id}/cooked-weight",
        headers=headers,
        json={"cooked_weight_grams": 1200},
    )
    assert edited_weight.status_code == 204, edited_weight.text
    occurrence = client.get(f"/api/v1/meal-plans/{plan_id}").json()["occurrences"][0]
    assert occurrence["serving_weight_grams"] == 300

    uncooked = client.delete(
        f"/api/v1/meal-plans/{plan_id}/batches/{batch_id}/cooked", headers=headers
    )
    assert uncooked.status_code == 204
    pantry = client.get("/api/v1/pantry-items").json()[0]
    assert pantry["on_hand_quantity"] == "100"
    assert pantry["reserved_quantity"] == "100"
    assert pantry["usable_quantity"] == "0"
    occurrence = client.get(f"/api/v1/meal-plans/{plan_id}").json()["occurrences"][0]
    assert occurrence["cooked_at"] is None
    assert occurrence["cooked_weight_grams"] is None
    cannot_weigh = client.patch(
        f"/api/v1/meal-plans/{plan_id}/batches/{batch_id}/cooked-weight",
        headers=headers,
        json={"cooked_weight_grams": 1000},
    )
    assert cannot_weigh.status_code == 422
    assert cannot_weigh.json()["code"] == "BATCH_NOT_COOKED"

    cooked_again = client.post(
        f"/api/v1/meal-plans/{plan_id}/batches/{batch_id}/cooked", headers=headers
    )
    assert cooked_again.status_code == 204
    pantry = client.get("/api/v1/pantry-items").json()[0]
    assert pantry["on_hand_quantity"] == "0"
    assert Decimal(pantry["reserved_quantity"]) == 0
