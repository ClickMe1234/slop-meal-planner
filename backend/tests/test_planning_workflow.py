from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    FoodRecord,
    MealBatch,
    MealOccurrence,
    MealPlan,
    PantryLot,
    PlanStatus,
    PortionAllocation,
    RecipeIngredient,
    RecipeVersion,
    ShoppingItem,
    ShoppingList,
)


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


def test_household_meal_group_defaults_and_split_generation(client, owner):
    owner_member_id = client.get("/api/v1/auth/me").json()["member_id"]
    second = client.post(
        "/api/v1/household-members",
        headers=_headers(owner),
        json={"name": "Bea"},
    )
    assert second.status_code == 201, second.text
    second_member_id = second.json()["id"]
    _set_dinner_target(client, owner, owner_member_id)
    _set_dinner_target(client, owner, second_member_id)

    defaults = client.get("/api/v1/households/current/meal-group-defaults")
    assert defaults.status_code == 200
    groups = defaults.json()["groups"]
    groups["dinner"] = [
        {"group_key": "owner-dinner", "member_ids": [owner_member_id]},
        {"group_key": "bea-dinner", "member_ids": [second_member_id]},
    ]
    updated = client.put(
        "/api/v1/households/current/meal-group-defaults",
        headers=_headers(owner),
        json={
            "expected_version": defaults.json()["household_version"],
            "groups": groups,
        },
    )
    assert updated.status_code == 200, updated.text
    assert len(updated.json()["groups"]["dinner"]) == 2

    recipes = [
        _create_recipe(client, owner, "Owner dinner", ["dinner"]),
        _create_recipe(client, owner, "Bea dinner", ["dinner"]),
    ]
    plan = _generate(
        client,
        owner,
        [recipe["id"] for recipe in recipes],
        [
            {
                "meal_date": "2026-09-01",
                "meal_type": "dinner",
                "meal_group_key": "owner-dinner",
                "participant_member_ids": [owner_member_id],
                "batch_key": "owner-batch",
            },
            {
                "meal_date": "2026-09-01",
                "meal_type": "dinner",
                "meal_group_key": "bea-dinner",
                "participant_member_ids": [second_member_id],
                "batch_key": "bea-batch",
            },
        ],
    )
    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    mains = [item for item in detail["occurrences"] if item["component_slot"] == 0]
    assert {item["meal_group_key"] for item in mains} == {
        "owner-dinner",
        "bea-dinner",
    }
    assert {item["recipe_id"] for item in mains} == {recipe["id"] for recipe in recipes}
    assert {portion["member_id"] for item in mains for portion in item["portions"]} == {
        owner_member_id,
        second_member_id,
    }


def test_duplicate_member_group_is_rejected_and_uncooked_plan_can_be_regrouped(client, owner):
    owner_member_id = client.get("/api/v1/auth/me").json()["member_id"]
    second = client.post(
        "/api/v1/household-members",
        headers=_headers(owner),
        json={"name": "Cal"},
    ).json()
    _set_dinner_target(client, owner, owner_member_id)
    _set_dinner_target(client, owner, second["id"])
    recipes = [
        _create_recipe(client, owner, "Shared dinner", ["dinner"]),
        _create_recipe(client, owner, "Alternative dinner", ["dinner"]),
    ]
    duplicate = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Invalid split",
            "recipe_ids": [recipe["id"] for recipe in recipes],
            "slots": [
                {"meal_date": "2026-09-02", "meal_type": "dinner", "meal_group_key": "one", "participant_member_ids": [owner_member_id]},
                {"meal_date": "2026-09-02", "meal_type": "dinner", "meal_group_key": "two", "participant_member_ids": [owner_member_id]},
            ],
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "DUPLICATE_MEAL_PARTICIPANT"

    plan = _generate(
        client,
        owner,
        [recipe["id"] for recipe in recipes],
        [{
            "meal_date": "2026-09-02",
            "meal_type": "dinner",
            "participant_member_ids": [owner_member_id, second["id"]],
            "batch_key": "shared-batch",
        }],
    )
    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    existing = detail["occurrences"][0]
    edited = client.put(
        f"/api/v1/meal-plans/{plan['id']}/preserving-edit",
        headers=_headers(owner),
        json={
            "expected_plan_version": detail["plan"]["version"],
            "removed_dates": [],
            "calorie_boosts": [],
            "guest_days": [],
            "added_cook_days": [],
            "removed_cook_days": [],
            "recipe_swaps": [],
            "main_slots": [
                {
                    "meal_date": "2026-09-02",
                    "meal_type": "dinner",
                    "meal_group_key": "shared",
                    "participant_member_ids": [owner_member_id],
                    "batch_key": existing["batch_id"],
                },
                {
                    "meal_date": "2026-09-02",
                    "meal_type": "dinner",
                    "meal_group_key": "cal-separate",
                    "participant_member_ids": [second["id"]],
                    "batch_key": "new-cal-batch",
                },
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    assert len([item for item in edited.json()["occurrences"] if item["component_slot"] == 0]) == 2


def test_shopping_sources_combine_and_recipe_unit_preview(client, owner, session_factory):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    recipe = _create_recipe(
        client,
        owner,
        "Root vegetable tray",
        ["dinner"],
        ingredients=[
            {
                "original_text": "100 g carrots",
                "quantity": 100,
                "unit": "g",
                "quantity_grams": 100,
                "food_phrase": "carrots",
            },
            {
                "original_text": "50 g parsnips",
                "quantity": 50,
                "unit": "g",
                "quantity_grams": 50,
                "food_phrase": "parsnips",
            },
        ],
    )
    plan = _generate(
        client,
        owner,
        [recipe["id"]],
        [{
            "meal_date": "2026-08-03",
            "meal_type": "dinner",
            "participant_member_ids": [member_id],
        }],
    )
    accepted = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    assert accepted.status_code == 200, accepted.text
    shopping = client.get("/api/v1/shopping-lists/active").json()
    assert len(shopping["items"]) == 2
    assert all(item["recipe_count"] == 1 for item in shopping["items"])
    assert all(item["source_count"] == 1 for item in shopping["items"])

    first = shopping["items"][0]
    sources = client.get(
        f"/api/v1/shopping-lists/{shopping['id']}/items/{first['id']}/sources"
    )
    assert sources.status_code == 200, sources.text
    assert sources.json()["sources"][0]["recipe_title"] == "Root vegetable tray"
    assert sources.json()["editable"] is True

    unknown = client.post(
        f"/api/v1/shopping-lists/{shopping['id']}/ingredient-change/preview",
        json={
            "item_ids": [first["id"]],
            "target_name": first["display_name"],
            "target_unit": "cup",
        },
    )
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()["conversions"][0]["manual_quantity_required"] is True

    item_ids = [item["id"] for item in shopping["items"]]
    preview = client.post(
        f"/api/v1/shopping-lists/{shopping['id']}/ingredient-change/preview",
        json={
            "item_ids": item_ids,
            "target_name": "root vegetables",
            "target_unit": "g",
        },
    )
    assert preview.status_code == 200, preview.text
    assert all(
        not conversion["manual_quantity_required"]
        for conversion in preview.json()["conversions"]
    )
    changed = client.post(
        f"/api/v1/shopping-lists/{shopping['id']}/ingredient-change",
        headers=_headers(owner),
        json={
            "expected_list_version": shopping["version"],
            "item_ids": item_ids,
            "target_name": "root vegetables",
            "target_unit": "g",
            "manual_conversions": [],
        },
    )
    assert changed.status_code == 200, changed.text
    result = changed.json()
    assert result["shopping_list"]["id"] != shopping["id"]
    assert len(result["shopping_list"]["items"]) == 1
    assert result["shopping_list"]["items"][0]["display_name"] == "root vegetables"
    assert result["shopping_list"]["items"][0]["source_count"] == 2

    with session_factory() as db:
        latest = db.scalar(
            select(RecipeVersion)
            .where(RecipeVersion.recipe_id == recipe["id"])
            .order_by(RecipeVersion.version_number.desc())
        )
        rows = db.scalars(
            select(RecipeIngredient)
            .where(RecipeIngredient.recipe_version_id == latest.id)
            .order_by(RecipeIngredient.position)
        ).all()
        assert len(rows) == 2
        assert {row.food_phrase for row in rows} == {"root vegetables"}
        assert len({row.shopping_group_key for row in rows}) == 1
        assert all(row.shopping_measurement_overridden for row in rows)


def test_recipe_review_rebalances_constraints_and_rebuilds_current_shopping_list(
    client, owner, session_factory
):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    recipe = _create_recipe(
        client,
        owner,
        "Ingredient sync dinner",
        ["dinner"],
        ingredients=[{
            "original_text": "100 g spinach",
            "quantity": 100,
            "unit": "g",
            "quantity_grams": 100,
            "food_phrase": "spinach",
        }],
    )
    plan = _generate(
        client,
        owner,
        [recipe["id"]],
        [{
            "meal_date": "2026-08-10",
            "meal_type": "dinner",
            "participant_member_ids": [member_id],
        }],
    )
    with session_factory() as db:
        allocation = db.scalar(
            select(PortionAllocation)
            .join(
                MealOccurrence,
                MealOccurrence.id == PortionAllocation.meal_occurrence_id,
            )
            .join(MealBatch, MealBatch.id == MealOccurrence.batch_id)
            .where(MealBatch.meal_plan_id == plan["id"])
        )
        allocation.servings = Decimal("0.75")
        batch = db.scalar(select(MealBatch).where(MealBatch.meal_plan_id == plan["id"]))
        batch.servings = Decimal("0.75")
        db.commit()
    assert client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    ).status_code == 200
    previous_list = client.get("/api/v1/shopping-lists/active").json()
    current = client.get(f"/api/v1/recipes/{recipe['id']}").json()
    ingredient = current["ingredients"][0]
    reviewed = client.put(
        f"/api/v1/recipes/{recipe['id']}/review",
        headers=_headers(owner),
        json={
            "expected_version": current["version"],
            "title": current["title"],
            "yield_servings": current["yield_servings"],
            "minimum_servings": 1,
            "serving_increment": 1,
            "meal_types": current["meal_types"],
            "ingredients": [{
                "original_text": ingredient["original_text"],
                "quantity": 200,
                "unit": "g",
                "quantity_grams": 200,
                "food_phrase": ingredient["food_phrase"],
                "included": True,
                "optional": False,
                "needs_review": False,
                "shopping_excluded": False,
                "shopping_measurement_overridden": True,
            }],
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["plan_sync"]["shopping_list_rebuilt"] is True
    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    assert detail["occurrences"][0]["portions"][0]["servings"] == 1
    assert detail["occurrences"][0]["batch_servings"] == 1
    active = client.get("/api/v1/shopping-lists/active").json()
    assert active["id"] != previous_list["id"]
    assert active["items"][0]["exact_quantity"] == "200"

    with session_factory() as db:
        allocation = db.scalar(
            select(PortionAllocation)
            .join(
                MealOccurrence,
                MealOccurrence.id == PortionAllocation.meal_occurrence_id,
            )
            .join(MealBatch, MealBatch.id == MealOccurrence.batch_id)
            .where(MealBatch.meal_plan_id == plan["id"])
        )
        allocation.servings = Decimal("0.25")
        batch = db.scalar(select(MealBatch).where(MealBatch.meal_plan_id == plan["id"]))
        batch.servings = Decimal("0.25")
        db.commit()
    current = reviewed.json()
    ingredient = current["ingredients"][0]
    cleared = client.put(
        f"/api/v1/recipes/{recipe['id']}/review",
        headers=_headers(owner),
        json={
            "expected_version": current["version"],
            "title": current["title"],
            "yield_servings": current["yield_servings"],
            "minimum_servings": None,
            "serving_increment": None,
            "meal_types": current["meal_types"],
            "ingredients": [{
                "original_text": ingredient["original_text"],
                "quantity": 200,
                "unit": "g",
                "quantity_grams": 200,
                "food_phrase": ingredient["food_phrase"],
                "included": True,
                "optional": False,
                "needs_review": False,
                "shopping_excluded": False,
            }],
        },
    )
    assert cleared.status_code == 200, cleared.text
    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    assert detail["occurrences"][0]["portions"][0]["servings"] == 0.5
    assert detail["occurrences"][0]["batch_servings"] == 0.5

    with session_factory() as db:
        allocation = db.scalar(
            select(PortionAllocation)
            .join(
                MealOccurrence,
                MealOccurrence.id == PortionAllocation.meal_occurrence_id,
            )
            .join(MealBatch, MealBatch.id == MealOccurrence.batch_id)
            .where(MealBatch.meal_plan_id == plan["id"])
        )
        allocation.servings = Decimal("2")
        batch = db.scalar(select(MealBatch).where(MealBatch.meal_plan_id == plan["id"]))
        batch.servings = Decimal("2")
        db.commit()
    current = cleared.json()
    constrained = client.put(
        f"/api/v1/recipes/{recipe['id']}/review",
        headers=_headers(owner),
        json={
            "expected_version": current["version"],
            "title": current["title"],
            "yield_servings": current["yield_servings"],
            "minimum_servings": 0.25,
            "serving_increment": 2,
            "meal_types": current["meal_types"],
            "ingredients": [{
                "original_text": ingredient["original_text"],
                "quantity": 200,
                "unit": "g",
                "quantity_grams": 200,
                "food_phrase": ingredient["food_phrase"],
                "included": True,
                "optional": False,
                "needs_review": False,
                "shopping_excluded": False,
            }],
        },
    )
    assert constrained.status_code == 200, constrained.text
    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    assert detail["occurrences"][0]["portions"][0]["servings"] == 0.25
    assert detail["occurrences"][0]["batch_servings"] == 0.25


def test_planner_serving_constraints_update_only_the_rule_and_refresh_ready_plan(
    client, owner, session_factory
):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    recipe = _create_recipe(
        client,
        owner,
        "Planner limit dinner",
        ["dinner"],
        ingredients=[{
            "original_text": "2 eggs",
            "quantity": 2,
            "unit": "item",
            "food_phrase": "eggs",
        }],
    )
    plan = _generate(
        client,
        owner,
        [recipe["id"]],
        [{
            "meal_date": "2026-08-12",
            "meal_type": "dinner",
            "participant_member_ids": [member_id],
        }],
    )
    with session_factory() as db:
        allocation = db.scalar(
            select(PortionAllocation)
            .join(MealOccurrence, MealOccurrence.id == PortionAllocation.meal_occurrence_id)
            .join(MealBatch, MealBatch.id == MealOccurrence.batch_id)
            .where(MealBatch.meal_plan_id == plan["id"])
        )
        allocation.servings = Decimal("0.75")
        batch = db.scalar(select(MealBatch).where(MealBatch.meal_plan_id == plan["id"]))
        batch.servings = Decimal("0.75")
        db.commit()

    current = client.get(f"/api/v1/recipes/{recipe['id']}").json()
    updated = client.put(
        f"/api/v1/recipes/{recipe['id']}/serving-constraints",
        headers=_headers(owner),
        json={
            "expected_version": current["version"],
            "minimum_servings": 1,
            "serving_increment": 0.5,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["plan_sync"]["plans_updated"] == 1
    assert Decimal(updated.json()["minimum_servings"]) == Decimal("1")
    assert Decimal(updated.json()["serving_increment"]) == Decimal("0.5")

    detail = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    occurrence = detail["occurrences"][0]
    assert occurrence["recipe_version"] == current["version"] + 1
    assert Decimal(str(occurrence["minimum_servings"])) == Decimal("1")
    assert Decimal(str(occurrence["serving_increment"])) == Decimal("0.5")
    assert occurrence["portions"][0]["servings"] == 1
    assert occurrence["batch_servings"] == 1
    with session_factory() as db:
        latest = db.scalar(
            select(RecipeVersion)
            .where(RecipeVersion.recipe_id == recipe["id"])
            .order_by(RecipeVersion.version_number.desc())
        )
        assert len(latest.ingredients) == 1
        assert latest.ingredients[0].original_text == "2 eggs"

    stale = client.put(
        f"/api/v1/recipes/{recipe['id']}/serving-constraints",
        headers=_headers(owner),
        json={
            "expected_version": current["version"],
            "minimum_servings": None,
            "serving_increment": None,
        },
    )
    assert stale.status_code == 409
    incomplete = client.put(
        f"/api/v1/recipes/{recipe['id']}/serving-constraints",
        headers=_headers(owner),
        json={
            "expected_version": updated.json()["version"],
            "minimum_servings": 1,
            "serving_increment": None,
        },
    )
    assert incomplete.status_code == 422


def test_recipe_review_never_rewrites_a_cooked_ready_batch(
    client, owner, session_factory
):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id)
    recipe = _create_recipe(
        client,
        owner,
        "Cooked constraint dinner",
        ["dinner"],
        ingredients=[{
            "original_text": "100 g spinach",
            "quantity": 100,
            "unit": "g",
            "quantity_grams": 100,
            "food_phrase": "spinach",
        }],
    )
    plan = _generate(
        client,
        owner,
        [recipe["id"]],
        [{
            "meal_date": "2026-08-11",
            "meal_type": "dinner",
            "participant_member_ids": [member_id],
        }],
    )
    before = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    occurrence = before["occurrences"][0]
    cooked = client.post(
        f"/api/v1/meal-plans/{plan['id']}/batches/{occurrence['batch_id']}/cooked",
        headers=_headers(owner),
    )
    assert cooked.status_code == 204, cooked.text
    with session_factory() as db:
        cooked_version_id = db.get(MealBatch, occurrence["batch_id"]).recipe_version_id

    current = client.get(f"/api/v1/recipes/{recipe['id']}").json()
    ingredient = current["ingredients"][0]
    reviewed = client.put(
        f"/api/v1/recipes/{recipe['id']}/review",
        headers=_headers(owner),
        json={
            "expected_version": current["version"],
            "title": current["title"],
            "yield_servings": current["yield_servings"],
            "minimum_servings": 2,
            "serving_increment": 1,
            "meal_types": current["meal_types"],
            "ingredients": [{
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
    assert reviewed.json()["plan_sync"]["plans_updated"] == 0
    assert reviewed.json()["plan_sync"]["cooked_batches_unchanged"] == 1
    after = client.get(f"/api/v1/meal-plans/{plan['id']}").json()["occurrences"][0]
    with session_factory() as db:
        assert db.get(MealBatch, occurrence["batch_id"]).recipe_version_id == cooked_version_id
    assert after["portions"] == occurrence["portions"]
    assert after["batch_servings"] == occurrence["batch_servings"]


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


def test_calorie_boosts_raise_daily_portions_and_guests_scale_the_batch(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id, calorie_target=500)
    recipe = _create_recipe(client, owner, "Cycling day dinner", ["dinner"])

    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Active day with guests",
            "recipe_ids": [recipe["id"]],
            "start_date": "2026-07-20",
            "end_date": "2026-07-20",
            "slots": [
                {
                    "meal_date": "2026-07-20",
                    "meal_type": "dinner",
                    "participant_member_ids": [member_id],
                }
            ],
            "calorie_boosts": [
                {
                    "meal_date": "2026-07-20",
                    "member_id": member_id,
                    "calories": 500,
                }
            ],
            "guest_days": [{"meal_date": "2026-07-20", "guest_count": 2}],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["calorie_boosts"] == [
        {"meal_date": "2026-07-20", "member_id": member_id, "calories": "500", "meal_allocations": []}
    ]
    assert response.json()["guest_days"] == [
        {"meal_date": "2026-07-20", "guest_count": 2, "meal_types": []}
    ]
    detail = client.get(f"/api/v1/meal-plans/{response.json()['id']}").json()
    occurrence = detail["occurrences"][0]
    assert float(occurrence["portions"][0]["servings"]) == 2
    assert float(occurrence["guest_servings"]) == 4
    assert float(occurrence["batch_servings"]) == 6


def test_preserving_edit_removes_day_and_adjustments_without_changing_recipes(
    client, owner
):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id, calorie_target=500)
    recipe = _create_recipe(client, owner, "Keep this dinner", ["dinner"])
    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Editable week",
            "recipe_ids": [recipe["id"]],
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "slots": [
                {
                    "meal_date": meal_date,
                    "meal_type": "dinner",
                    "participant_member_ids": [member_id],
                    "batch_key": "shared-dinner",
                }
                for meal_date in ("2026-08-03", "2026-08-04", "2026-08-05")
            ],
            "calorie_boosts": [
                {
                    "meal_date": "2026-08-03",
                    "member_id": member_id,
                    "calories": 500,
                }
            ],
            "guest_days": [
                {"meal_date": "2026-08-04", "guest_count": 2}
            ],
        },
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    accepted = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    assert accepted.status_code == 200, accepted.text
    before = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    original_recipe_ids = {item["recipe_id"] for item in before["occurrences"]}

    edited = client.put(
        f"/api/v1/meal-plans/{plan['id']}/preserving-edit",
        headers=_headers(owner),
        json={
            "expected_plan_version": accepted.json()["version"],
            "removed_dates": ["2026-08-03"],
            "calorie_boosts": [],
            "guest_days": [],
            "added_cook_days": [],
        },
    )

    assert edited.status_code == 200, edited.text
    detail = edited.json()
    assert detail["plan"]["status"] == "accepted"
    assert detail["plan"]["start_date"] == "2026-08-04"
    assert detail["plan"]["calorie_boosts"] == []
    assert detail["plan"]["guest_days"] == []
    assert {item["meal_date"] for item in detail["occurrences"]} == {
        "2026-08-04",
        "2026-08-05",
    }
    assert {item["recipe_id"] for item in detail["occurrences"]} == original_recipe_ids
    assert all(
        item["planned_cook_date"] == "2026-08-04"
        for item in detail["occurrences"]
    )
    assert all(float(item["portions"][0]["servings"]) == 1 for item in detail["occurrences"])
    assert all(float(item["guest_servings"]) == 0 for item in detail["occurrences"])
    shopping = client.get("/api/v1/shopping-lists/active")
    assert shopping.status_code == 200
    assert shopping.json()["meal_plan_id"] == plan["id"]


def test_preserving_edit_adds_new_recipe_only_from_new_cook_day(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id, calorie_target=500)
    recipes = [
        _create_recipe(client, owner, title, ["dinner"])
        for title in ("First dinner", "Second dinner", "Third dinner")
    ]
    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Split cooking week",
            "recipe_ids": [item["id"] for item in recipes],
            "start_date": "2026-08-10",
            "end_date": "2026-08-13",
            "slots": [
                {
                    "meal_date": meal_date,
                    "meal_type": "dinner",
                    "participant_member_ids": [member_id],
                    "batch_key": "week-dinner",
                    "food_safety_acknowledged": True,
                }
                for meal_date in (
                    "2026-08-10",
                    "2026-08-11",
                    "2026-08-12",
                    "2026-08-13",
                )
            ],
        },
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    accepted = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    assert accepted.status_code == 200, accepted.text
    before = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    original_recipe_id = before["occurrences"][0]["recipe_id"]
    selected_recipe_id = next(
        item["id"] for item in recipes if item["id"] != original_recipe_id
    )

    edited = client.put(
        f"/api/v1/meal-plans/{plan['id']}/preserving-edit",
        headers=_headers(owner),
        json={
            "expected_plan_version": accepted.json()["version"],
            "removed_dates": [],
            "calorie_boosts": [],
            "guest_days": [],
            "added_cook_days": [
                {
                    "meal_date": "2026-08-12",
                    "meal_type": "dinner",
                    "recipe_id": selected_recipe_id,
                }
            ],
        },
    )

    assert edited.status_code == 200, edited.text
    by_date = {
        item["meal_date"]: item
        for item in edited.json()["occurrences"]
        if item["component_slot"] == 0
    }
    assert by_date["2026-08-10"]["recipe_id"] == original_recipe_id
    assert by_date["2026-08-11"]["recipe_id"] == original_recipe_id
    assert by_date["2026-08-12"]["recipe_id"] == selected_recipe_id
    assert by_date["2026-08-13"]["recipe_id"] == by_date["2026-08-12"]["recipe_id"]
    assert by_date["2026-08-12"]["planned_cook_date"] == "2026-08-12"


def test_preserving_edit_swaps_a_batch_recipe(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id, calorie_target=500)
    recipes = [
        _create_recipe(client, owner, title, ["dinner"])
        for title in ("Original batch", "Chosen replacement")
    ]
    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Swappable batch",
            "recipe_ids": [item["id"] for item in recipes],
            "start_date": "2026-08-17",
            "end_date": "2026-08-18",
            "slots": [
                {
                    "meal_date": meal_date,
                    "meal_type": "dinner",
                    "participant_member_ids": [member_id],
                    "batch_key": "dinner",
                }
                for meal_date in ("2026-08-17", "2026-08-18")
            ],
        },
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    accepted = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    before = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    batch_id = before["occurrences"][0]["batch_id"]
    original_recipe_id = before["occurrences"][0]["recipe_id"]
    selected_recipe_id = next(
        item["id"] for item in recipes if item["id"] != original_recipe_id
    )

    edited = client.put(
        f"/api/v1/meal-plans/{plan['id']}/preserving-edit",
        headers=_headers(owner),
        json={
            "expected_plan_version": accepted.json()["version"],
            "recipe_swaps": [
                {"batch_id": batch_id, "recipe_id": selected_recipe_id}
            ],
        },
    )

    assert edited.status_code == 200, edited.text
    assert {
        item["recipe_id"]
        for item in edited.json()["occurrences"]
        if item["component_slot"] == 0
    } == {selected_recipe_id}


def test_preserving_edit_removes_cook_day_and_uses_previous_batch(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    _set_dinner_target(client, owner, member_id, calorie_target=500)
    recipes = [
        _create_recipe(client, owner, title, ["dinner"])
        for title in ("Earlier batch", "Later batch")
    ]
    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Merge cooking batches",
            "recipe_ids": [item["id"] for item in recipes],
            "start_date": "2026-08-24",
            "end_date": "2026-08-27",
            "slots": [
                {
                    "meal_date": meal_date,
                    "meal_type": "dinner",
                    "participant_member_ids": [member_id],
                    "batch_key": "first" if meal_date < "2026-08-26" else "second",
                }
                for meal_date in (
                    "2026-08-24",
                    "2026-08-25",
                    "2026-08-26",
                    "2026-08-27",
                )
            ],
        },
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    accepted = client.post(
        f"/api/v1/meal-plans/{plan['id']}/accept", headers=_headers(owner)
    )
    before = client.get(f"/api/v1/meal-plans/{plan['id']}").json()
    by_date_before = {
        item["meal_date"]: item
        for item in before["occurrences"]
        if item["component_slot"] == 0
    }
    previous_batch_id = by_date_before["2026-08-25"]["batch_id"]
    previous_recipe_id = by_date_before["2026-08-25"]["recipe_id"]
    assert by_date_before["2026-08-26"]["batch_id"] != previous_batch_id

    edited = client.put(
        f"/api/v1/meal-plans/{plan['id']}/preserving-edit",
        headers=_headers(owner),
        json={
            "expected_plan_version": accepted.json()["version"],
            "removed_cook_days": [
                {"meal_date": "2026-08-26", "meal_type": "dinner"}
            ],
        },
    )

    assert edited.status_code == 200, edited.text
    mains = [
        item for item in edited.json()["occurrences"] if item["component_slot"] == 0
    ]
    assert {item["batch_id"] for item in mains} == {previous_batch_id}
    assert {item["recipe_id"] for item in mains} == {previous_recipe_id}
    assert {item["planned_cook_date"] for item in mains} == {"2026-08-24"}


def test_day_adjustments_apply_only_to_selected_meals(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    target = client.put(
        f"/api/v1/household-members/{member_id}/target",
        headers=_headers(owner),
        json={
            "mode": "calorie",
            "calorie_target": 1000,
            "tolerance_percent": 5,
            "allocations": [
                {"meal_type": "dinner", "percentage": 50},
                {"meal_type": "snack", "percentage": 50},
            ],
        },
    )
    assert target.status_code == 200, target.text
    dinner = _create_recipe(client, owner, "Guest dinner", ["dinner"])
    snack = _create_recipe(client, owner, "Cycling snack", ["snack"])

    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Focused adjustments",
            "recipe_ids": [dinner["id"], snack["id"]],
            "slots": [
                {"meal_date": "2026-07-20", "meal_type": "dinner", "participant_member_ids": [member_id]},
                {"meal_date": "2026-07-20", "meal_type": "snack", "participant_member_ids": [member_id]},
            ],
            "calorie_boosts": [{
                "meal_date": "2026-07-20",
                "member_id": member_id,
                "calories": 500,
                "meal_allocations": [{"meal_type": "snack", "percentage": 100}],
            }],
            "guest_days": [{
                "meal_date": "2026-07-20",
                "guest_count": 2,
                "meal_types": ["dinner"],
            }],
        },
    )

    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/meal-plans/{response.json()['id']}").json()
    occurrences = {item["meal_type"]: item for item in detail["occurrences"]}
    assert float(occurrences["dinner"]["portions"][0]["servings"]) == 1
    assert float(occurrences["dinner"]["guest_servings"]) == 2
    assert float(occurrences["snack"]["portions"][0]["servings"]) == 2
    assert float(occurrences["snack"]["guest_servings"]) == 0


def test_calorie_boost_is_distributed_using_meal_sliders(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    target = client.put(
        f"/api/v1/household-members/{member_id}/target",
        headers=_headers(owner),
        json={
            "mode": "calorie",
            "calorie_target": 1000,
            "tolerance_percent": 5,
            "allocations": [
                {"meal_type": "breakfast", "percentage": 30},
                {"meal_type": "lunch", "percentage": 30},
                {"meal_type": "snack", "percentage": 40},
            ],
        },
    )
    assert target.status_code == 200, target.text
    recipes = [
        _create_recipe(client, owner, "Boost breakfast", ["breakfast"]),
        _create_recipe(client, owner, "Boost lunch", ["lunch"]),
        _create_recipe(client, owner, "Boost snack", ["snack"]),
    ]

    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Distributed cycling boost",
            "recipe_ids": [recipe["id"] for recipe in recipes],
            "slots": [
                {
                    "meal_date": "2026-07-20",
                    "meal_type": meal_type,
                    "participant_member_ids": [member_id],
                }
                for meal_type in ("breakfast", "lunch", "snack")
            ],
            "calorie_boosts": [{
                "meal_date": "2026-07-20",
                "member_id": member_id,
                "calories": 1400,
                "meal_allocations": [
                    {"meal_type": "breakfast", "percentage": 30},
                    {"meal_type": "lunch", "percentage": 30},
                    {"meal_type": "snack", "percentage": 40},
                ],
            }],
        },
    )

    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/meal-plans/{response.json()['id']}").json()
    servings = {
        occurrence["meal_type"]: float(occurrence["portions"][0]["servings"])
        for occurrence in detail["occurrences"]
    }
    assert servings == {"breakfast": 1.5, "lunch": 1.5, "snack": 2.0}


def test_large_calorie_boost_can_exceed_the_standard_two_serving_limit(client, owner):
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
    snack = _create_recipe(client, owner, "Long ride snack", ["snack"])

    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "High energy snack",
            "recipe_ids": [snack["id"]],
            "slots": [{
                "meal_date": "2026-07-20",
                "meal_type": "snack",
                "participant_member_ids": [member_id],
            }],
            "calorie_boosts": [{
                "meal_date": "2026-07-20",
                "member_id": member_id,
                "calories": 1000,
                "meal_allocations": [{"meal_type": "snack", "percentage": 100}],
            }],
        },
    )

    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/meal-plans/{response.json()['id']}").json()
    assert float(detail["occurrences"][0]["portions"][0]["servings"]) == 3


def test_calorie_boost_requires_a_calorie_target(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    target = client.put(
        f"/api/v1/household-members/{member_id}/target",
        headers=_headers(owner),
        json={
            "mode": "macros",
            "protein_target_g": 30,
            "carbohydrate_target_g": 50,
            "fat_target_g": 20,
            "tolerance_percent": 5,
            "allocations": [{"meal_type": "dinner", "percentage": 100}],
        },
    )
    assert target.status_code == 200, target.text
    recipe = _create_recipe(client, owner, "Macro dinner", ["dinner"])

    response = client.post(
        "/api/v1/meal-plans/generate",
        headers=_headers(owner),
        json={
            "name": "Invalid boost",
            "recipe_ids": [recipe["id"]],
            "slots": [{"meal_date": "2026-07-20", "meal_type": "dinner", "participant_member_ids": [member_id]}],
            "calorie_boosts": [{"meal_date": "2026-07-20", "member_id": member_id, "calories": 500}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "CALORIE_BOOST_REQUIRES_CALORIE_TARGET"


def test_recipe_ingredient_search_uses_current_saved_recipe_ingredients(client, owner):
    spinach = _create_recipe(
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
            {
                "id": "baby spinach",
                "term": "baby spinach",
                "name": "baby spinach",
                "recipes": [{"id": spinach["id"], "title": "Spinach pasta"}],
            }
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
    assert "image_url" in detail["occurrences"][0]
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
            },
            {
                "original_text": "50 g spinach",
                "food_phrase": "spinach",
                "quantity_grams": 50,
                "unit": "g",
            },
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
        spinach_food = FoodRecord(
            provider="test",
            provider_record_id="fresh-spinach",
            dataset_version="1",
            name="Spinach",
        )
        db.add(spinach_food)
        db.flush()
        latest_version = db.scalar(
            select(RecipeVersion)
            .where(RecipeVersion.recipe_id == recipe["id"])
            .order_by(RecipeVersion.version_number.desc())
        )
        spinach_ingredient = db.scalar(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_version_id == latest_version.id,
                RecipeIngredient.food_phrase == "spinach",
            )
        )
        spinach_ingredient.food_record_id = spinach_food.id
        db.add(
            PantryLot(
                household_id=stored_plan.household_id,
                food_record_id=spinach_food.id,
                display_name="Spinach",
                initial_quantity=10000,
                unit="g",
            )
        )
        stale = ShoppingList(
            household_id=stored_plan.household_id,
            meal_plan_id=stored_plan.id,
            name="Stale pre-accept list",
            active=True,
        )
        db.add(stale)
        db.flush()
        db.add_all([
            ShoppingItem(
                shopping_list_id=stale.id,
                display_name="rice",
                exact_quantity=1,
                purchase_quantity=1,
                unit="g",
                category="Other",
                checked=True,
                manual=False,
            ),
            ShoppingItem(
                shopping_list_id=stale.id,
                display_name="old manual item",
                exact_quantity=1,
                purchase_quantity=1,
                unit="item",
                category="Other",
                checked=True,
                manual=True,
            ),
        ])
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
    assert active["items"][0]["checked"] is False
    assert {item["display_name"] for item in active["items"]}.isdisjoint(
        {"spinach", "old manual item"}
    )

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
