from decimal import Decimal

from sqlalchemy import select

from app.models import FoodRecord, Household, Recipe, RecipeIngredient, RecipeVersion
from app.services.pantry_matching import pantry_name_similarity


def test_pantry_item_can_be_renamed_and_set_to_an_absolute_quantity(client, owner):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    created = client.post(
        "/api/v1/pantry-items",
        headers=headers,
        json={"display_name": "Rice", "quantity": "1000", "unit": "g"},
    ).json()

    updated = client.patch(
        f"/api/v1/pantry-items/{created['id']}",
        headers=headers,
        json={
            "expected_version": created["version"],
            "display_name": "Basmati rice",
            "quantity": "750",
        },
    )

    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert payload["display_name"] == "Basmati rice"
    assert Decimal(payload["on_hand_quantity"]) == Decimal("750")
    assert payload["on_hand_quantity_display"] == "750 g"
    assert payload["version"] == created["version"] + 1


def test_pantry_edit_rejects_a_stale_version(client, owner):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    created = client.post(
        "/api/v1/pantry-items",
        headers=headers,
        json={"display_name": "Rice", "quantity": "1", "unit": "kg"},
    ).json()

    response = client.patch(
        f"/api/v1/pantry-items/{created['id']}",
        headers=headers,
        json={"expected_version": created["version"] + 1, "display_name": "Rice", "quantity": "1"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"


def test_unreserved_pantry_item_can_be_deleted(client, owner):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    created = client.post(
        "/api/v1/pantry-items",
        headers=headers,
        json={"display_name": "Rice", "quantity": "1", "unit": "kg"},
    ).json()

    deleted = client.delete(f"/api/v1/pantry-items/{created['id']}", headers=headers)

    assert deleted.status_code == 204
    assert client.get("/api/v1/pantry-items").json() == []


def test_multiple_pantry_items_can_be_deleted_in_one_request(client, owner):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    created = [
        client.post(
            "/api/v1/pantry-items",
            headers=headers,
            json={"display_name": name, "quantity": "1", "unit": "count"},
        ).json()
        for name in ("Rice", "Beans", "Pasta")
    ]

    response = client.post(
        "/api/v1/pantry-items/batch-delete",
        headers=headers,
        json={"item_ids": [created[0]["id"], created[2]["id"]]},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "deleted_ids": [created[0]["id"], created[2]["id"]],
        "blocked": [],
    }
    remaining = client.get("/api/v1/pantry-items").json()
    assert [item["display_name"] for item in remaining] == ["Beans"]


def test_pantry_item_can_be_flagged_for_use_soon(client, owner):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    created = client.post(
        "/api/v1/pantry-items",
        headers=headers,
        json={"display_name": "Spinach", "quantity": "200", "unit": "g"},
    ).json()
    assert created["use_soon"] is False

    updated = client.patch(
        f"/api/v1/pantry-items/{created['id']}",
        headers=headers,
        json={
            "expected_version": created["version"],
            "display_name": created["display_name"],
            "quantity": created["on_hand_quantity"],
            "use_soon": True,
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["use_soon"] is True
    assert updated.json()["version"] == created["version"] + 1


def test_rice_can_be_suggested_and_confirmed_as_basmati_rice(
    client, owner, session_factory
):
    with session_factory() as db:
        household = db.scalar(select(Household))
        food = FoodRecord(
            provider="test",
            provider_record_id="basmati-rice",
            dataset_version="1",
            name="Basmati rice",
        )
        recipe = Recipe(household_id=household.id, title="Basmati bowl")
        db.add_all([food, recipe])
        db.flush()
        version = RecipeVersion(
            recipe_id=recipe.id,
            version_number=1,
            title=recipe.title,
            yield_servings=1,
        )
        db.add(version)
        db.flush()
        db.add(
            RecipeIngredient(
                recipe_version_id=version.id,
                position=0,
                original_text="100 g basmati rice",
                quantity_grams=100,
                food_phrase="Basmati rice",
                parsed_food_phrase="Basmati rice",
                food_record_id=food.id,
            )
        )
        db.commit()
        food_id = food.id

    headers = {"X-CSRF-Token": owner["csrf_token"]}
    pantry = client.post(
        "/api/v1/pantry-items",
        headers=headers,
        json={"display_name": "Rice", "quantity": "1", "unit": "kg"},
    ).json()

    suggestions = client.get("/api/v1/pantry-match-suggestions")
    assert suggestions.status_code == 200, suggestions.text
    candidate = suggestions.json()[0]["candidates"][0]
    assert candidate["food_record_id"] == food_id
    assert candidate["display_name"] == "Basmati rice"
    assert candidate["confidence"] >= 0.8

    confirmed = client.put(
        f"/api/v1/pantry-items/{pantry['id']}/food-match",
        headers=headers,
        json={"expected_version": pantry["version"], "food_record_id": food_id},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["food_record_id"] == food_id
    assert client.get("/api/v1/pantry-match-suggestions").json() == []


def test_pantry_name_similarity_requires_confirmation_for_broad_matches(db):
    assert pantry_name_similarity(db, "rice", "basmati rice") >= 0.8
    assert pantry_name_similarity(db, "rice", "spinach") < 0.45
