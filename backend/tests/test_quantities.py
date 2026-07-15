from decimal import Decimal

import pytest

from app.services.quantities import (
    canonical_quantity_unit,
    format_quantity,
    round_purchase_quantity,
    round_quantity,
)
from app.services.quantity_normalization import normalize_stored_quantities
from app.models import (
    Household,
    PantryLot,
    PantryReservation,
    PantryTransaction,
    ShoppingItem,
    ShoppingList,
)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("430.5", "g", "431"),
        ("250.4", "ml", "250"),
        ("1.236", "litres", "1.24"),
        ("3.1", "item", "4"),
        ("6.01", "cloves", "7"),
        ("0.1875", "tsp", "0.25"),
        ("1.125", "cups", "1.125"),
        ("2.345", "scoop", "2.35"),
        ("0.1", "g", "1"),
        ("-1.2", "item", "-2"),
    ],
)
def test_round_quantity_uses_unit_appropriate_precision(value, unit, expected):
    assert round_quantity(Decimal(value), unit) == Decimal(expected)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("430.1", "g", "431"),
        ("1.231", "l", "1.24"),
        ("1.01", "tbsp", "1.25"),
        ("1.126", "cup", "1.25"),
        ("3.01", "eggs", "4"),
    ],
)
def test_purchase_quantities_always_round_up(value, unit, expected):
    assert round_purchase_quantity(Decimal(value), unit) == Decimal(expected)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("1020.5829", "g", "1,021 g"),
        ("1.20", "l", "1.2 l"),
        ("0.25", "tsp", "¼ tsp"),
        ("0.5", "cup", "½ cup"),
        ("1.125", "cup", "1⅛ cups"),
        ("1", "clove", "1 clove"),
        ("2", "clove", "2 cloves"),
        ("0", "ml", "0 ml"),
    ],
)
def test_format_quantity_removes_noise_and_uses_cooking_fractions(value, unit, expected):
    assert format_quantity(Decimal(value), unit) == expected


def test_unit_aliases_share_one_storage_unit():
    assert canonical_quantity_unit(" Tablespoons. ") == "tbsp"
    assert canonical_quantity_unit("counts") == "item"


def test_existing_shopping_and_pantry_values_are_normalized_idempotently(db):
    household = Household(name="Rounded household")
    db.add(household)
    db.flush()
    lot = PantryLot(
        household_id=household.id,
        display_name="Stock",
        initial_quantity=Decimal("1.236"),
        unit="litres",
    )
    shopping_list = ShoppingList(
        household_id=household.id,
        name="Current shopping list",
        active=True,
    )
    db.add_all([lot, shopping_list])
    db.flush()
    movement = PantryTransaction(
        pantry_lot_id=lot.id,
        quantity_delta=Decimal("-0.004"),
        reason="test",
    )
    reservation = PantryReservation(
        pantry_lot_id=lot.id,
        meal_batch_id="test-batch",
        quantity=Decimal("0.333"),
        unit="litres",
    )
    item = ShoppingItem(
        shopping_list_id=shopping_list.id,
        display_name="Seasoning",
        exact_quantity=Decimal("1.121"),
        purchase_quantity=Decimal("1.121"),
        unit="tablespoons",
        category="Cupboard",
        checked=False,
        manual=False,
    )
    db.add_all([movement, reservation, item])
    db.flush()

    result = normalize_stored_quantities(db)

    assert result.pantry_lots_changed == 1
    assert result.transactions_changed == 1
    assert result.reservations_changed == 1
    assert result.shopping_items_changed == 1
    assert result.lists_marked == 1
    assert lot.unit == "l"
    assert lot.initial_quantity == Decimal("1.24")
    assert movement.quantity_delta == Decimal("-0.01")
    assert reservation.unit == "l"
    assert reservation.quantity == Decimal("0.33")
    assert item.unit == "tbsp"
    assert item.exact_quantity == Decimal("1")
    assert item.purchase_quantity == Decimal("1.25")
    assert shopping_list.rebuild_recommended is True

    repeated = normalize_stored_quantities(db)
    assert repeated.pantry_lots_changed == 0
    assert repeated.transactions_changed == 0
    assert repeated.reservations_changed == 0
    assert repeated.shopping_items_changed == 0
    assert repeated.lists_marked == 0


def test_pantry_api_rounds_storage_and_returns_human_display(client, owner):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    created = client.post(
        "/api/v1/pantry-items",
        headers=headers,
        json={"display_name": "Stock", "quantity": "1.236", "unit": "litres"},
    )

    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["unit"] == "l"
    assert Decimal(payload["initial_quantity"]) == Decimal("1.24")
    assert payload["initial_quantity_display"] == "1.24 l"
    assert payload["on_hand_quantity_display"] == "1.24 l"

    adjusted = client.post(
        f"/api/v1/pantry-items/{payload['id']}/adjust",
        headers=headers,
        json={"quantity_delta": "0.006", "reason": "test"},
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["on_hand_quantity_display"] == "1.25 l"
