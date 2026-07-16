from datetime import datetime, timezone

from sqlalchemy import select

from app.models import MealPlan, PlanStatus, RecipeVersion, ShoppingItem, ShoppingList


PUBLISHER_NUTRITION = {
    "basis": "per serving",
    "energy_kcal": 500,
    "protein_g": 30,
    "carbohydrate_g": 55,
    "fat_g": 18,
}


def _headers(owner):
    return {"X-CSRF-Token": owner["csrf_token"]}


def _set_dinner_target(client, owner, member_id, calorie_target=500):
    response = client.put(
        f"/api/v1/household-members/{member_id}/target",
        headers=_headers(owner),
        json={
            "mode": "calorie",
            "calorie_target": calorie_target,
            "tolerance_percent": 5,
            "allocations": [{"meal_type": "dinner", "percentage": 100}],
        },
    )
    assert response.status_code == 200, response.text


def _create_recipe(client, owner, title, meal_types, ingredients=None, nutrition=None):
    response = client.post(
        "/api/v1/recipes",
        headers=_headers(owner),
        json={
            "title": title,
            "yield_servings": 1,
            "source_type": "url",
            "source_url": f"https://example.com/{title.casefold().replace(' ', '-')}",
            "publisher": "Example",
            "publisher_nutrition": nutrition or PUBLISHER_NUTRITION,
            "meal_types": meal_types,
            "ingredients": ingredients or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_food(client, owner, name):
    response = client.post(
        "/api/v1/foods",
        headers=_headers(owner),
        json={
            "provider": "test",
            "provider_record_id": name.casefold().replace(" ", "-"),
            "dataset_version": "fixture-1",
            "name": name,
            "basis_amount": 100,
            "basis_unit": "g",
            "nutrients": [
                {"code": "energy_kcal", "amount": 100, "unit": "kcal"},
                {"code": "protein_g", "amount": 10, "unit": "g"},
                {"code": "carbohydrate_g", "amount": 10, "unit": "g"},
                {"code": "fat_g", "amount": 2, "unit": "g"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _generate(
    client,
    owner,
    recipe_ids,
    slots,
    *,
    start_date=None,
    end_date=None,
    must_use_food_record_ids=None,
    exclude_food_record_ids=None,
):
    payload = {"name": "Test plan", "recipe_ids": recipe_ids, "slots": slots}
    if start_date is not None:
        payload["start_date"] = start_date
        payload["end_date"] = end_date
    payload["must_use_food_record_ids"] = must_use_food_record_ids or []
    payload["exclude_food_record_ids"] = exclude_food_record_ids or []
    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_recipe_meal_types_are_optional_filterable_and_required_by_planner(client, owner):
    tagged = _create_recipe(client, owner, "Lunch bowl", ["lunch", "dinner"])
    untagged = _create_recipe(client, owner, "Unsorted bowl", [])

    assert tagged["meal_types"] == ["dinner", "lunch"]
    assert tagged["planner_eligible"] is True
    assert untagged["planner_eligible"] is False
    assert any("meal type" in warning.lower() for warning in untagged["planner_warnings"])

    lunches = client.get("/api/v1/recipes?meal_type=lunch").json()["items"]
    breakfasts = client.get("/api/v1/recipes?meal_type=breakfast").json()["items"]
    assert [recipe["id"] for recipe in lunches] == [tagged["id"]]
    assert breakfasts == []

    side = _create_recipe(client, owner, "Flexible side", ["side", "snack"])
    flexible = client.get("/api/v1/recipes?meal_type=side&meal_type=snack").json()["items"]
    assert [recipe["id"] for recipe in flexible] == [side["id"]]

    empty_attendance = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Invalid plan",
            "recipe_ids": [tagged["id"]],
            "slots": [
                {
                    "meal_date": "2026-07-20",
                    "meal_type": "lunch",
                    "participant_member_ids": [],
                }
            ],
        },
    )
    assert empty_attendance.status_code == 422
    assert empty_attendance.json()["code"] == "VALIDATION_ERROR"


def test_recipe_ingredient_search_uses_current_saved_recipe_ingredients(client, owner):
    _create_recipe(
        client,
        owner,
        "Spinach pasta",
        ["dinner"],
        ingredients=[
            {
                "original_text": "200 g baby spinach",
                "food_phrase": "baby spinach",
                "quantity_grams": 200,
                "unit": "g",
            }
        ],
    )
    _create_recipe(
        client,
        owner,
        "Broccoli pasta",
        ["dinner"],
        ingredients=[
            {
                "original_text": "1 head broccoli",
                "food_phrase": "broccoli",
                "quantity": 1,
                "unit": "head",
            }
        ],
    )

    response = client.get("/api/v1/recipe-ingredients?q=spin")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {"id": "baby spinach", "term": "baby spinach", "name": "baby spinach"}
        ],
        "total": 1,
    }


def test_plan_specific_ingredient_terms_prefer_matching_saved_recipe(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    broccoli = _create_recipe(
        client,
        owner,
        "Broccoli pasta",
        ["dinner"],
        ingredients=[
            {
                "original_text": "200 g broccoli",
                "food_phrase": "broccoli",
                "quantity_grams": 200,
                "unit": "g",
            }
        ],
    )
    spinach = _create_recipe(
        client,
        owner,
        "Spinach pasta",
        ["dinner"],
        ingredients=[
            {
                "original_text": "200 g spinach",
                "food_phrase": "spinach",
                "quantity_grams": 200,
                "unit": "g",
            }
        ],
    )

    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Prefer spinach",
            "recipe_ids": [broccoli["id"], spinach["id"]],
            "slots": [
                {
                    "meal_date": "2026-07-20",
                    "meal_type": "dinner",
                    "participant_member_ids": [member_id],
                }
            ],
            "prefer_ingredient_terms": ["spinach", "garlic"],
        },
    )

    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/meal-plans/{response.json()['id']}").json()
    assert detail["occurrences"][0]["recipe_id"] == spinach["id"]
    guidance = next(
        item
        for item in detail["plan"]["diagnostics"]
        if item["code"] == "GENERATION_GUIDANCE"
    )
    assert guidance["prefer_ingredient_terms"] == ["spinach", "garlic"]


def test_sides_apply_to_the_whole_batch_and_rebalance_all_plan_portions(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    main = _create_recipe(
        client,
        owner,
        "Four hundred calorie main",
        ["dinner"],
        nutrition={
            "basis": "per serving",
            "energy_kcal": 400,
            "protein_g": 24,
            "carbohydrate_g": 44,
            "fat_g": 14,
        },
    )
    side = _create_recipe(
        client,
        owner,
        "One hundred calorie side",
        ["side"],
        nutrition={
            "basis": "per serving",
            "energy_kcal": 100,
            "protein_g": 6,
            "carbohydrate_g": 11,
            "fat_g": 3,
        },
    )
    snack = _create_recipe(
        client,
        owner,
        "Snack used as side",
        ["snack"],
        ingredients=[{
            "original_text": "100 g carrots",
            "food_phrase": "carrots",
            "quantity_grams": 100,
            "unit": "g",
        }],
        nutrition={
            "basis": "per serving",
            "energy_kcal": 100,
            "protein_g": 6,
            "carbohydrate_g": 11,
            "fat_g": 3,
        },
    )
    plan = _generate(
        client,
        owner,
        [main["id"]],
        [
            {
                "meal_date": meal_date,
                "meal_type": "dinner",
                "participant_member_ids": [member_id],
                "batch_key": "shared-dinner",
            }
            for meal_date in ("2026-07-20", "2026-07-21")
        ],
    )
    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    main_batch_id = detail["occurrences"][0]["batch_id"]

    added = client.post(
        f"/api/v1/meal-plans/{plan['id']}/batches/{main_batch_id}/sides",
        headers=_headers(owner),
        json={
            "recipe_id": side["id"],
            "expected_plan_version": detail["plan"]["version"],
        },
    )
    assert added.status_code == 200, added.text
    with_side = added.json()
    side_occurrences = [
        item for item in with_side["occurrences"] if item["component_slot"] == 1
    ]
    assert len(side_occurrences) == 2
    assert {item["parent_batch_id"] for item in side_occurrences} == {main_batch_id}
    assert {item["recipe_id"] for item in side_occurrences} == {side["id"]}
    assert all(item["portions"][0]["member_id"] == member_id for item in side_occurrences)
    assert [day["totals"]["energy_kcal"] for day in with_side["daily_nutrition"]] == [
        500,
        500,
    ]

    added_snack = client.post(
        f"/api/v1/meal-plans/{plan['id']}/batches/{main_batch_id}/sides",
        headers=_headers(owner),
        json={
            "recipe_id": snack["id"],
            "expected_plan_version": with_side["plan"]["version"],
        },
    )
    assert added_snack.status_code == 200, added_snack.text
    two_sides = added_snack.json()
    assert {item["component_slot"] for item in two_sides["occurrences"]} == {0, 1, 2}

    limit = client.post(
        f"/api/v1/meal-plans/{plan['id']}/batches/{main_batch_id}/sides",
        headers=_headers(owner),
        json={
            "recipe_id": side["id"],
            "expected_plan_version": two_sides["plan"]["version"],
        },
    )
    assert limit.status_code == 422
    assert limit.json()["code"] == "SIDE_LIMIT_REACHED"

    side_batch_id = next(
        item["batch_id"]
        for item in two_sides["occurrences"]
        if item["component_slot"] == 1
    )
    removed = client.request(
        "DELETE",
        f"/api/v1/meal-plans/{plan['id']}/batches/{side_batch_id}/sides",
        headers=_headers(owner),
        json={"expected_plan_version": two_sides["plan"]["version"]},
    )
    assert removed.status_code == 200, removed.text
    assert {item["component_slot"] for item in removed.json()["occurrences"]} == {0, 2}
    accepted = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    assert accepted.status_code == 200, accepted.text
    shopping = client.get("/api/v1/shopping-lists/active").json()
    carrots = next(item for item in shopping["items"] if item["display_name"] == "carrots")
    assert float(carrots["exact_quantity"]) == 200


def test_snack_batches_only_accept_additional_snack_recipes(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    target = client.put(
        f"/api/v1/household-members/{member_id}/target",
        headers=_headers(owner),
        json={
            "mode": "calorie",
            "calorie_target": 500,
            "tolerance_percent": 5,
            "allocations": [{"meal_type": "snack", "percentage": 100}],
        },
    )
    assert target.status_code == 200, target.text
    main = _create_recipe(client, owner, "Main snack", ["snack"])
    side_only = _create_recipe(client, owner, "Side only", ["side"])
    plan = _generate(
        client,
        owner,
        [main["id"]],
        [{
            "meal_date": "2026-07-20",
            "meal_type": "snack",
            "participant_member_ids": [member_id],
        }],
    )
    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    blocked = client.post(
        f"/api/v1/meal-plans/{plan['id']}/batches/{detail['occurrences'][0]['batch_id']}/sides",
        headers=_headers(owner),
        json={
            "recipe_id": side_only["id"],
            "expected_plan_version": detail["plan"]["version"],
        },
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "RECIPE_MEAL_TYPE_MISMATCH"


def test_grouped_batch_supports_per_date_attendance_preferences_and_replacement(client, owner):
    owner_member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, owner_member_id)
    partner = client.post(
        "/api/v1/household-members",
        headers=_headers(owner),
        json={"name": "Partner"},
    ).json()
    _set_dinner_target(client, owner, partner["id"], calorie_target=250)
    targets = client.get("/api/v1/household-members/targets").json()
    assert {target["member_id"]: float(target["calorie_target"]) for target in targets} == {
        owner_member_id: 500,
        partner["id"]: 250,
    }
    preferred = client.post(
        f"/api/v1/household-members/{owner_member_id}/restrictions",
        headers=_headers(owner),
        json={"kind": "prefer", "value": "spinach"},
    )
    assert preferred.status_code == 201, preferred.text

    broccoli = _create_recipe(
        client,
        owner,
        "Broccoli dinner",
        ["dinner"],
        [{"original_text": "100 g broccoli", "quantity_grams": 100, "unit": "g"}],
    )
    spinach = _create_recipe(
        client,
        owner,
        "Spinach dinner",
        ["dinner"],
        [{"original_text": "100 g spinach", "quantity_grams": 100, "unit": "g"}],
    )
    plan = _generate(
        client,
        owner,
        [broccoli["id"], spinach["id"]],
        [
            {
                "meal_date": "2026-07-20",
                "meal_type": "dinner",
                "participant_member_ids": [owner_member_id, partner["id"]],
                "batch_key": "dinner-monday",
            },
            {
                "meal_date": "2026-07-21",
                "meal_type": "dinner",
                "participant_member_ids": [owner_member_id],
                "batch_key": "dinner-monday",
            },
        ],
        start_date="2026-07-19",
        end_date="2026-07-22",
    )

    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    assert detail["plan"]["start_date"] == "2026-07-19"
    assert detail["plan"]["end_date"] == "2026-07-22"
    assert {item["recipe_id"] for item in detail["occurrences"]} == {spinach["id"]}
    assert [len(item["portions"]) for item in detail["occurrences"]] == [2, 1]
    assert float(detail["occurrences"][0]["batch_servings"]) == 2.5
    assert detail["daily_nutrition"][0]["totals"]["energy_kcal"] == 750
    assert detail["daily_nutrition"][1]["totals"]["energy_kcal"] == 500

    occurrence_id = detail["occurrences"][0]["id"]
    replaced = client.put(
        f"/api/v1/meal-plans/{plan['id']}/occurrences/{occurrence_id}/recipe",
        headers=_headers(owner),
        json={
            "recipe_id": broccoli["id"],
            "expected_plan_version": detail["plan"]["version"],
        },
    )
    assert replaced.status_code == 200, replaced.text
    replaced_detail = replaced.json()
    assert {item["recipe_id"] for item in replaced_detail["occurrences"]} == {
        broccoli["id"]
    }
    assert [len(item["portions"]) for item in replaced_detail["occurrences"]] == [2, 1]
    assert float(replaced_detail["occurrences"][0]["batch_servings"]) == 2.5


def test_infeasible_plan_can_be_retried_in_best_effort_mode(
    client, owner, session_factory
):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    recipe = _create_recipe(client, owner, "Very light dinner", ["dinner"])
    # Make the only recipe far below the target at every supported portion.
    with session_factory() as db:
        version = db.scalar(select(RecipeVersion).where(RecipeVersion.recipe_id == recipe["id"]))
        version.publisher_nutrition = {
            "basis": "per serving",
            "energy_kcal": 100,
            "protein_g": 5,
            "carbohydrate_g": 10,
            "fat_g": 3,
        }
        db.commit()

    payload = {
        "name": "Best effort plan",
        "recipe_ids": [recipe["id"]],
        "slots": [{
            "meal_date": "2026-07-20",
            "meal_type": "dinner",
            "participant_member_ids": [member_id],
        }],
    }
    infeasible = client.post(
        "/api/v1/meal-plans/generate", headers=_headers(owner), json=payload
    )
    assert infeasible.status_code == 422
    assert infeasible.json()["code"] == "NUTRITION_TARGET_INFEASIBLE"
    assert infeasible.json()["actions"][0]["kind"] == "retry_best_effort"
    assert infeasible.json()["detail"] == (
        "The available recipes could not meet every daily nutrition target."
    )
    assert infeasible.json()["issues"] == [
        {
            "date": "2026-07-20",
            "member": "owner",
            "violations": [
                {
                    "nutrient": "calories",
                    "actual": "200",
                    "low": "475",
                    "high": "525",
                    "kind": "range",
                    "message": "Calories: 200 kcal (allowed 475–525 kcal)",
                }
            ],
        }
    ]

    retried = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={**payload, "ignore_nutrition_tolerances": True},
    )
    assert retried.status_code == 201, retried.text
    assert any(
        item["code"] == "NUTRITION_TOLERANCE_RELAXED"
        for item in retried.json()["diagnostics"]
    )
    detail = client.get(f"/api/v1/meal-plans/{retried.json()['id']}").json()
    assert detail["occurrences"][0]["portions"] == [
        {"member_id": member_id, "servings": 2.0}
    ]

    replacement_payload = {
        "recipe_id": recipe["id"],
        "expected_plan_version": detail["plan"]["version"],
    }
    strict_replacement = client.put(
        f"/api/v1/meal-plans/{retried.json()['id']}/occurrences/{detail['occurrences'][0]['id']}/recipe",
        headers=_headers(owner),
        json=replacement_payload,
    )
    assert strict_replacement.status_code == 422
    assert strict_replacement.json()["code"] == "NUTRITION_TARGET_INFEASIBLE"
    assert strict_replacement.json()["actions"][0]["kind"] == "retry_best_effort"

    relaxed_replacement = client.put(
        f"/api/v1/meal-plans/{retried.json()['id']}/occurrences/{detail['occurrences'][0]['id']}/recipe",
        headers=_headers(owner),
        json={**replacement_payload, "ignore_nutrition_tolerances": True},
    )
    assert relaxed_replacement.status_code == 200, relaxed_replacement.text
    assert any(
        item["code"] == "REPLACEMENT_NUTRITION_TOLERANCE_RELAXED"
        for item in relaxed_replacement.json()["plan"]["diagnostics"]
    )


def test_generation_treats_meal_splits_as_soft_daily_targets(
    client, owner, session_factory
):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    target = client.put(
        f"/api/v1/household-members/{member_id}/target",
        headers=_headers(owner),
        json={
            "mode": "calorie",
            "calorie_target": 1000,
            "tolerance_percent": 5,
            "allocations": [
                {"meal_type": "breakfast", "percentage": 50},
                {"meal_type": "dinner", "percentage": 50},
            ],
        },
    )
    assert target.status_code == 200, target.text
    breakfast = _create_recipe(client, owner, "Light breakfast", ["breakfast"])
    dinner = _create_recipe(client, owner, "Heavy dinner", ["dinner"])
    with session_factory() as db:
        breakfast_version = db.scalar(
            select(RecipeVersion).where(RecipeVersion.recipe_id == breakfast["id"])
        )
        dinner_version = db.scalar(
            select(RecipeVersion).where(RecipeVersion.recipe_id == dinner["id"])
        )
        breakfast_version.publisher_nutrition = {
            **PUBLISHER_NUTRITION,
            "energy_kcal": 460,
        }
        dinner_version.publisher_nutrition = {
            **PUBLISHER_NUTRITION,
            "energy_kcal": 540,
        }
        db.commit()

    generated = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Soft meal splits",
            "recipe_ids": [breakfast["id"], dinner["id"]],
            "slots": [
                {
                    "meal_date": "2026-07-20",
                    "meal_type": "breakfast",
                    "participant_member_ids": [member_id],
                },
                {
                    "meal_date": "2026-07-20",
                    "meal_type": "dinner",
                    "participant_member_ids": [member_id],
                },
            ],
        },
    )

    assert generated.status_code == 201, generated.text
    detail = client.get(f"/api/v1/meal-plans/{generated.json()['id']}").json()
    assert [item["portions"][0]["servings"] for item in detail["occurrences"]] == [
        1.0,
        1.0,
    ]


def test_replacement_preserves_plan_specific_ingredient_guidance(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    must_food = _create_food(client, owner, "Must use greens")
    excluded_food = _create_food(client, owner, "Excluded nuts")
    required = _create_recipe(
        client,
        owner,
        "Required dinner",
        ["dinner"],
        [
            {
                "original_text": "100 g must use greens",
                "quantity_grams": 100,
                "unit": "g",
                "food_record_id": must_food["id"],
            }
        ],
    )
    excluded = _create_recipe(
        client,
        owner,
        "Excluded dinner",
        ["dinner"],
        [
            {
                "original_text": "100 g excluded nuts",
                "quantity_grams": 100,
                "unit": "g",
                "food_record_id": excluded_food["id"],
            }
        ],
    )
    neutral = _create_recipe(client, owner, "Neutral dinner", ["dinner"])
    plan = _generate(
        client,
        owner,
        [required["id"], excluded["id"], neutral["id"]],
        [
            {
                "meal_date": "2026-07-20",
                "meal_type": "dinner",
                "participant_member_ids": [member_id],
            }
        ],
        must_use_food_record_ids=[must_food["id"]],
        exclude_food_record_ids=[excluded_food["id"]],
    )
    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    occurrence_id = detail["occurrences"][0]["id"]

    excluded_swap = client.put(
        f"/api/v1/meal-plans/{plan['id']}/occurrences/{occurrence_id}/recipe",
        headers=_headers(owner),
        json={
            "recipe_id": excluded["id"],
            "expected_plan_version": detail["plan"]["version"],
        },
    )
    assert excluded_swap.status_code == 422
    assert excluded_swap.json()["code"] == "PLAN_EXCLUDED_INGREDIENT"
    assert excluded_swap.json()["actions"][0]["kind"] == "replace_recipe"

    missing_must_use = client.put(
        f"/api/v1/meal-plans/{plan['id']}/occurrences/{occurrence_id}/recipe",
        headers=_headers(owner),
        json={
            "recipe_id": neutral["id"],
            "expected_plan_version": detail["plan"]["version"],
        },
    )
    assert missing_must_use.status_code == 422
    assert missing_must_use.json()["code"] == "MUST_USE_INGREDIENT_INFEASIBLE"
    assert missing_must_use.json()["actions"][0]["kind"] == "replace_recipe"


def test_accept_is_atomic_and_reviewed_shopping_exclusion_refreshes_ready_plan(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    recipe = _create_recipe(
        client,
        owner,
        "Seasoned dinner",
        ["dinner"],
        [{"original_text": "salt and pepper to taste", "food_phrase": "salt and pepper"}],
    )
    plan = _generate(
        client,
        owner,
        [recipe["id"]],
        [
            {
                "meal_date": "2026-07-20",
                "meal_type": "dinner",
                "participant_member_ids": [member_id],
            }
        ],
    )

    premature_list = client.post(
        "/api/v1/shopping-lists/build",
        headers=_headers(owner),
        json={"meal_plan_id": plan["id"], "name": "Too early"},
    )
    assert premature_list.status_code == 422
    assert premature_list.json()["code"] == "PLAN_NOT_ACCEPTED"

    blocked = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    assert blocked.status_code == 422, blocked.text
    problem = blocked.json()
    assert problem["code"] == "SHOPPING_REVIEW_REQUIRED"
    assert problem["actions"][0]["recipe_id"] == recipe["id"]
    assert "focusIngredient=" in problem["actions"][0]["href"]
    assert "Do not add to shopping list" in problem["actions"][0]["suggestion"]
    assert client.get(f"/api/v1/meal-plans/{plan['id']}").json()["plan"]["status"] == "ready"

    current = client.get(f"/api/v1/recipes/{recipe['id']}").json()
    ingredient = current["ingredients"][0]
    reviewed = client.put(
        f"/api/v1/recipes/{recipe['id']}/review",
        headers=_headers(owner),
        json={
            "expected_version": current["version"],
            "title": current["title"],
            "yield_servings": current["yield_servings"],
            "meal_types": current["meal_types"],
            "ingredients": [
                {
                    "original_text": ingredient["original_text"],
                    "quantity": ingredient["quantity"],
                    "unit": ingredient["unit"],
                    "quantity_grams": ingredient["quantity_grams"],
                    "food_phrase": ingredient["food_phrase"],
                    "preparation": ingredient["preparation"],
                    "included": ingredient["included"],
                    "optional": ingredient["optional"],
                    "needs_review": ingredient["needs_review"],
                    "shopping_excluded": True,
                    "food_record_id": ingredient["food_record_id"],
                }
            ],
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["ingredients"][0]["shopping_excluded"] is True

    accepted = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    shopping = client.get("/api/v1/shopping-lists/active")
    assert shopping.status_code == 200, shopping.text
    assert shopping.json()["meal_plan_id"] == plan["id"]
    assert shopping.json()["items"] == []

    accepted_again = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    assert accepted_again.status_code == 200, accepted_again.text
    assert client.get("/api/v1/shopping-lists/active").json()["id"] == shopping.json()["id"]


def test_accept_revalidates_recipe_tags_and_new_household_restrictions(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    untagged_later = _create_recipe(
        client,
        owner,
        "Retagged dinner",
        ["dinner"],
        [{"original_text": "1 tsp seasoning", "quantity": 1, "unit": "tsp"}],
    )
    tag_plan = _generate(
        client,
        owner,
        [untagged_later["id"]],
        [
            {
                "meal_date": "2026-07-20",
                "meal_type": "dinner",
                "participant_member_ids": [member_id],
            }
        ],
    )
    current = client.get(f"/api/v1/recipes/{untagged_later['id']}").json()
    ingredient = current["ingredients"][0]
    removed_tag = client.put(
        f"/api/v1/recipes/{untagged_later['id']}/review",
        headers=_headers(owner),
        json={
            "expected_version": current["version"],
            "title": current["title"],
            "yield_servings": current["yield_servings"],
            "meal_types": [],
            "ingredients": [
                {
                    "original_text": ingredient["original_text"],
                    "quantity": ingredient["quantity"],
                    "unit": ingredient["unit"],
                    "quantity_grams": ingredient["quantity_grams"],
                    "food_phrase": ingredient["food_phrase"],
                    "preparation": ingredient["preparation"],
                    "included": ingredient["included"],
                    "optional": ingredient["optional"],
                    "needs_review": ingredient["needs_review"],
                    "shopping_excluded": ingredient["shopping_excluded"],
                    "food_record_id": ingredient["food_record_id"],
                }
            ],
        },
    )
    assert removed_tag.status_code == 200, removed_tag.text
    tag_blocked = client.post(
        f"/api/v1/meal-plans/{tag_plan['id']}/accept", headers=_headers(owner)
    )
    assert tag_blocked.status_code == 422
    assert tag_blocked.json()["code"] == "RECIPE_MEAL_TYPE_REVIEW_REQUIRED"
    assert tag_blocked.json()["actions"][0]["kind"] == "review_recipe"

    restricted_later = _create_recipe(
        client,
        owner,
        "Peanut dinner",
        ["dinner"],
        [{"original_text": "100 g peanuts", "quantity_grams": 100, "unit": "g"}],
    )
    restriction_plan = _generate(
        client,
        owner,
        [restricted_later["id"]],
        [
            {
                "meal_date": "2026-07-21",
                "meal_type": "dinner",
                "participant_member_ids": [member_id],
            }
        ],
    )
    added = client.post(
        f"/api/v1/household-members/{member_id}/restrictions",
        headers=_headers(owner),
        json={"kind": "allergy", "value": "peanuts", "hard": True},
    )
    assert added.status_code == 201, added.text
    restriction_blocked = client.post(
        f"/api/v1/meal-plans/{restriction_plan['id']}/accept",
        headers=_headers(owner),
    )
    assert restriction_blocked.status_code == 422
    assert restriction_blocked.json()["code"] == "RECIPE_RESTRICTED"
    assert restriction_blocked.json()["actions"][0]["kind"] == "replace_recipe"


def test_accept_replaces_a_legacy_pre_accept_shopping_list(
    client, owner, session_factory
):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    recipe = _create_recipe(
        client,
        owner,
        "Rice dinner",
        ["dinner"],
        [
            {
                "original_text": "100 g rice",
                "food_phrase": "rice",
                "quantity_grams": 100,
                "unit": "g",
            }
        ],
    )
    plan = _generate(
        client,
        owner,
        [recipe["id"]],
        [
            {
                "meal_date": "2026-07-20",
                "meal_type": "dinner",
                "participant_member_ids": [member_id],
            }
        ],
    )

    with session_factory() as db:
        stored_plan = db.get(MealPlan, plan["id"])
        stale = ShoppingList(
            household_id=stored_plan.household_id,
            meal_plan_id=stored_plan.id,
            name="Stale pre-accept list",
            active=True,
        )
        db.add(stale)
        db.flush()
        db.add(
            ShoppingItem(
                shopping_list_id=stale.id,
                display_name="rice",
                exact_quantity=1,
                purchase_quantity=1,
                unit="g",
                category="Other",
                checked=False,
                manual=False,
            )
        )
        db.commit()
        stale_id = stale.id

    accepted = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    assert accepted.status_code == 200, accepted.text
    active = client.get("/api/v1/shopping-lists/active").json()
    assert active["id"] != stale_id
    assert active["meal_plan_id"] == plan["id"]
    assert len(active["items"]) == 1
    assert active["items"][0]["display_name"] == "rice"
    assert active["items"][0]["exact_quantity"] == "100"
    assert active["items"][0]["exact_quantity_display"] == "100 g"

    with session_factory() as db:
        assert db.get(ShoppingList, stale_id).active is False


def test_legacy_accepted_plan_without_list_can_be_recovered(client, owner, session_factory):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    recipe = _create_recipe(client, owner, "Legacy dinner", ["dinner"])
    plan = _generate(
        client,
        owner,
        [recipe["id"]],
        [
            {
                "meal_date": "2026-07-20",
                "meal_type": "dinner",
                "participant_member_ids": [member_id],
            }
        ],
    )
    with session_factory() as db:
        stored = db.get(MealPlan, plan["id"])
        stored.status = PlanStatus.ACCEPTED.value
        stored.accepted_at = datetime.now(timezone.utc)
        stored.version += 1
        db.commit()

    recovered = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    assert recovered.status_code == 200, recovered.text
    with session_factory() as db:
        lists = db.scalars(
            select(ShoppingList).where(ShoppingList.meal_plan_id == plan["id"])
        ).all()
        assert len(lists) == 1


def test_accepting_a_new_plan_supersedes_the_current_plan(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    recipe = _create_recipe(client, owner, "Replacement dinner", ["dinner"])

    def generate_for(meal_date):
        return _generate(
            client,
            owner,
            [recipe["id"]],
            [{
                "meal_date": meal_date,
                "meal_type": "dinner",
                "participant_member_ids": [member_id],
            }],
        )

    first = generate_for("2026-07-20")
    assert client.post(
        f"/api/v1/meal-plans/{first['id']}/accept", headers=_headers(owner)
    ).status_code == 200

    second = generate_for("2026-07-27")
    assert client.post(
        f"/api/v1/meal-plans/{second['id']}/accept", headers=_headers(owner)
    ).status_code == 200

    plans = client.get("/api/v1/meal-plans").json()
    statuses = {plan["id"]: plan["status"] for plan in plans}
    assert statuses[first["id"]] == "superseded"
    assert statuses[second["id"]] == "accepted"
    assert [plan["id"] for plan in plans if plan["status"] == "accepted"] == [second["id"]]
    assert client.get("/api/v1/shopping-lists/active").json()["meal_plan_id"] == second["id"]
