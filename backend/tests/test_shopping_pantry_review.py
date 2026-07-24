from decimal import Decimal

from sqlalchemy import select

from app.models import (
    FoodRecord,
    Household,
    PantryLot,
    PantryTransaction,
    ShoppingItem,
    ShoppingList,
)


def _review_fixture(session_factory):
    with session_factory() as db:
        household = db.scalar(select(Household))
        food = FoodRecord(
            provider="test",
            provider_record_id="review-chickpeas",
            dataset_version="1",
            name="Chickpeas",
        )
        pantry = PantryLot(
            household_id=household.id,
            food_record_id=food.id,
            display_name="Chickpeas",
            initial_quantity=2,
            unit="count",
        )
        shopping_list = ShoppingList(household_id=household.id, name="Current")
        db.add_all([food, pantry, shopping_list])
        db.flush()
        item = ShoppingItem(
            shopping_list_id=shopping_list.id,
            food_record_id=food.id,
            display_name="Chickpeas",
            exact_quantity=400,
            purchase_quantity=400,
            unit="g",
            pantry_unit_conflicts=[
                {
                    "pantry_lot_id": pantry.id,
                    "display_name": pantry.display_name,
                    "usable_quantity": "2",
                    "unit": "count",
                    "usable_quantity_display": "2 count",
                }
            ],
        )
        db.add(item)
        db.commit()
        return shopping_list.id, item.id, item.version, pantry.id


def test_user_can_apply_an_explicit_incompatible_pantry_amount(
    client, owner, session_factory
):
    list_id, item_id, version, pantry_id = _review_fixture(session_factory)
    response = client.post(
        f"/api/v1/shopping-lists/{list_id}/items/{item_id}/pantry-review",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={
            "expected_version": version,
            "decision": "use",
            "pantry_lot_id": pantry_id,
            "pantry_quantity": "1",
            "requirement_quantity": "250",
            "requirement_unit": "g",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["removed"] is False
    assert Decimal(payload["item"]["exact_quantity"]) == Decimal("150")
    assert payload["item"]["pantry_unit_conflicts"] == []
    assert Decimal(payload["pantry_item"]["on_hand_quantity"]) == Decimal("1")
    with session_factory() as db:
        transaction = db.scalar(select(PantryTransaction))
        assert transaction.quantity_delta == Decimal("-1")
        assert transaction.reference_type == "shopping_item"
        assert transaction.reference_id == item_id


def test_user_can_keep_the_full_purchase_without_changing_pantry(
    client, owner, session_factory
):
    list_id, item_id, version, _ = _review_fixture(session_factory)
    response = client.post(
        f"/api/v1/shopping-lists/{list_id}/items/{item_id}/pantry-review",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={"expected_version": version, "decision": "buy"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["removed"] is False
    assert Decimal(payload["item"]["exact_quantity"]) == Decimal("400")
    assert payload["item"]["pantry_unit_conflicts"] == []
    with session_factory() as db:
        assert db.scalar(select(PantryTransaction)) is None


def test_user_can_confirm_an_unresolved_name_match_on_an_existing_list(
    client, owner, session_factory
):
    with session_factory() as db:
        household = db.scalar(select(Household))
        pantry = PantryLot(
            household_id=household.id,
            display_name="courgette",
            initial_quantity=4,
            unit="count",
        )
        shopping_list = ShoppingList(
            household_id=household.id,
            name="Current shopping list",
            active=True,
        )
        db.add_all([pantry, shopping_list])
        db.flush()
        item = ShoppingItem(
            shopping_list_id=shopping_list.id,
            display_name="courgette",
            exact_quantity=700,
            purchase_quantity=700,
            unit="g",
            source_name_keys=["courgette", "stem:courgett"],
        )
        db.add(item)
        db.commit()
        list_id, item_id, version, pantry_id = (
            shopping_list.id,
            item.id,
            item.version,
            pantry.id,
        )

    active = client.get("/api/v1/shopping-lists/active")
    assert active.status_code == 200, active.text
    suggestion = active.json()["items"][0]["pantry_match_suggestions"][0]
    assert suggestion["pantry_lot_id"] == pantry_id
    assert suggestion["display_name"] == "courgette"
    assert Decimal(suggestion["usable_quantity"]) == Decimal("4")

    response = client.post(
        f"/api/v1/shopping-lists/{list_id}/items/{item_id}/pantry-match",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={
            "expected_version": version,
            "pantry_lot_id": pantry_id,
            "decision": "match",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["removed"] is False
    assert payload["item"]["pantry_match_suggestions"] == []
    assert payload["item"]["pantry_confirmed_matches"] == [
        {
            "pantry_lot_id": pantry_id,
            "display_name": "courgette",
            "usable_quantity": "4",
            "unit": "item",
            "usable_quantity_display": "4 items",
            "confidence": 1.0,
            "fuzzy": False,
        }
    ]
    assert payload["item"]["pantry_unit_conflicts"][0]["pantry_lot_id"] == pantry_id
    with session_factory() as db:
        pantry = db.get(PantryLot, pantry_id)
        assert pantry.food_record_id is None
        assert pantry.shopping_name_keys == ["courgette", "stem:courgett"]

    undo = client.post(
        f"/api/v1/shopping-lists/{list_id}/items/{item_id}/pantry-match",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={
            "expected_version": payload["item"]["version"],
            "pantry_lot_id": pantry_id,
            "decision": "undo",
        },
    )
    assert undo.status_code == 200, undo.text
    undone_item = undo.json()["item"]
    assert undone_item["pantry_confirmed_matches"] == []
    assert undone_item["pantry_unit_conflicts"] == []
    assert undone_item["pantry_match_suggestions"][0]["pantry_lot_id"] == pantry_id
    with session_factory() as db:
        assert db.get(PantryLot, pantry_id).shopping_name_keys == []


def test_confirmed_fuzzy_match_names_the_pantry_item_without_using_stock(
    client, owner, session_factory
):
    with session_factory() as db:
        household = db.scalar(select(Household))
        pantry = PantryLot(
            household_id=household.id,
            display_name="Basmati rice",
            initial_quantity=500,
            unit="g",
        )
        shopping_list = ShoppingList(
            household_id=household.id,
            name="Current shopping list",
            active=True,
        )
        db.add_all([pantry, shopping_list])
        db.flush()
        item = ShoppingItem(
            shopping_list_id=shopping_list.id,
            display_name="rice",
            exact_quantity=400,
            purchase_quantity=400,
            unit="g",
            source_name_keys=["rice", "stem:rice"],
        )
        db.add(item)
        db.commit()
        list_id, item_id, version, pantry_id = (
            shopping_list.id,
            item.id,
            item.version,
            pantry.id,
        )

    response = client.post(
        f"/api/v1/shopping-lists/{list_id}/items/{item_id}/pantry-match",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={
            "expected_version": version,
            "pantry_lot_id": pantry_id,
            "decision": "match",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["removed"] is False
    assert Decimal(payload["item"]["exact_quantity"]) == Decimal("400")
    confirmed = payload["item"]["pantry_confirmed_matches"][0]
    assert confirmed["display_name"] == "Basmati rice"
    assert confirmed["fuzzy"] is True
    assert confirmed["confidence"] < 1


def test_fuzzy_match_is_suggested_across_distinct_food_records(
    client, owner, session_factory
):
    with session_factory() as db:
        household = db.scalar(select(Household))
        pantry_food = FoodRecord(
            provider="test",
            provider_record_id="plain-protein-powder",
            dataset_version="1",
            name="Protein powder",
        )
        shopping_food = FoodRecord(
            provider="test",
            provider_record_id="vanilla-protein-powder",
            dataset_version="1",
            name="Vanilla protein powder",
        )
        db.add_all([pantry_food, shopping_food])
        db.flush()
        pantry = PantryLot(
            household_id=household.id,
            food_record_id=pantry_food.id,
            display_name="protein powder",
            initial_quantity=500,
            unit="g",
        )
        shopping_list = ShoppingList(
            household_id=household.id,
            name="Current shopping list",
            active=True,
        )
        db.add_all([pantry, shopping_list])
        db.flush()
        item = ShoppingItem(
            shopping_list_id=shopping_list.id,
            food_record_id=shopping_food.id,
            display_name="vanilla protein powder",
            exact_quantity=120,
            purchase_quantity=120,
            unit="g",
            source_name_keys=[
                "vanilla protein powder",
                "stem:vanilla protein powder",
            ],
        )
        db.add(item)
        db.commit()
        pantry_id = pantry.id

    active = client.get("/api/v1/shopping-lists/active")

    assert active.status_code == 200, active.text
    suggestions = active.json()["items"][0]["pantry_match_suggestions"]
    assert suggestions[0]["pantry_lot_id"] == pantry_id
    assert suggestions[0]["display_name"] == "protein powder"
    assert suggestions[0]["confidence"] >= 0.9


def test_user_can_reject_an_unresolved_name_match(
    client, owner, session_factory
):
    with session_factory() as db:
        household = db.scalar(select(Household))
        pantry = PantryLot(
            household_id=household.id,
            display_name="courgette",
            initial_quantity=4,
            unit="count",
        )
        shopping_list = ShoppingList(
            household_id=household.id,
            name="Current shopping list",
            active=True,
        )
        db.add_all([pantry, shopping_list])
        db.flush()
        item = ShoppingItem(
            shopping_list_id=shopping_list.id,
            display_name="courgette",
            exact_quantity=700,
            purchase_quantity=700,
            unit="g",
            source_name_keys=["courgette", "stem:courgett"],
        )
        db.add(item)
        db.commit()
        list_id, item_id, version, pantry_id = (
            shopping_list.id,
            item.id,
            item.version,
            pantry.id,
        )

    response = client.post(
        f"/api/v1/shopping-lists/{list_id}/items/{item_id}/pantry-match",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={
            "expected_version": version,
            "pantry_lot_id": pantry_id,
            "decision": "reject",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["item"]["pantry_match_suggestions"] == []
    assert payload["item"]["pantry_unit_conflicts"] == []
    with session_factory() as db:
        pantry = db.get(PantryLot, pantry_id)
        assert pantry.shopping_name_keys == []
        assert pantry.rejected_shopping_name_keys == [
            "courgette",
            "stem:courgett",
        ]
