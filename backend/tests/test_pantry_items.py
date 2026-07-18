from decimal import Decimal


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
