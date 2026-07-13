def test_owner_setup_login_and_calorie_target(client, owner):
    csrf = owner["csrf_token"]
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "owner"

    member_id = me.json()["member_id"]
    response = client.put(
        f"/api/v1/household-members/{member_id}/target",
        headers={"X-CSRF-Token": csrf},
        json={
            "mode": "calorie",
            "calorie_target": 2000,
            "tolerance_percent": 10,
            "protein_min_g": 100,
            "allocations": [
                {"meal_type": "breakfast", "percentage": 25},
                {"meal_type": "lunch", "percentage": 30},
                {"meal_type": "dinner", "percentage": 35},
                {"meal_type": "snack", "percentage": 10},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["calorie_target"] == "2000.00"


def test_csrf_is_required(client, owner):
    response = client.post("/api/v1/household-members", json={"name": "Partner"})
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"


def test_rejects_conflicting_target_modes(client, owner):
    member_id = client.get("/api/v1/auth/me").json()["member_id"]
    response = client.put(
        f"/api/v1/household-members/{member_id}/target",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={
            "mode": "calorie",
            "calorie_target": 2000,
            "protein_target_g": 150,
            "allocations": [{"meal_type": "dinner", "percentage": 100}],
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_collaborator_must_replace_temporary_password(client, owner):
    created = client.post(
        "/api/v1/auth/users",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={
            "username": "helper",
            "temporary_password": "temporary-password-123",
        },
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "helper", "password": "temporary-password-123"},
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    blocked = client.get("/api/v1/recipes")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"X-CSRF-Token": csrf},
        json={
            "current_password": "temporary-password-123",
            "new_password": "a-new-private-password-456",
        },
    )
    assert changed.status_code == 204
    assert client.get("/api/v1/recipes").status_code == 200
