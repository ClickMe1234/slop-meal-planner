from decimal import Decimal


def test_household_recipe_plan_pantry_and_shopping_loop(client, owner):
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
            "source_type": "custom",
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
    assert item["exact_quantity"] == "100.0000"
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
    assert purchased.json()[0]["reserved_quantity"] == "100.0000"
    assert purchased.json()[0]["usable_quantity"] == "0.0000"

    plan = client.get(f"/api/v1/meal-plans/{plan_id}").json()
    batch_id = plan["occurrences"][0]["batch_id"]
    cooked = client.post(
        f"/api/v1/meal-plans/{plan_id}/batches/{batch_id}/cooked", headers=headers
    )
    assert cooked.status_code == 204
    pantry = client.get("/api/v1/pantry-items").json()[0]
    assert pantry["on_hand_quantity"] == "0.0000"
    assert Decimal(pantry["reserved_quantity"]) == 0
