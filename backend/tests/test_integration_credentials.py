from sqlalchemy import select

from app.models import IntegrationCredential, User


def test_owner_can_save_and_remove_usda_key_without_exposing_it(client, owner, session_factory):
    headers = {"X-CSRF-Token": owner["csrf_token"]}
    api_key = "private-usda-key-123456"

    initial = client.get("/api/v1/system/integrations/usda")
    assert initial.status_code == 200
    assert initial.json()["configured"] is False
    assert initial.json()["source"] in {"missing", "demo"}

    saved = client.put(
        "/api/v1/system/integrations/usda",
        json={"api_key": api_key},
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "configured": True,
        "source": "saved",
        "signup_url": "https://fdc.nal.usda.gov/api-key-signup.html",
    }
    assert api_key not in saved.text

    status = client.get("/api/v1/system/integrations/usda")
    assert status.json()["source"] == "saved"
    assert api_key not in status.text

    with session_factory() as db:
        owner_user = db.scalar(select(User).where(User.username == "owner"))
        credential = db.scalar(
            select(IntegrationCredential).where(
                IntegrationCredential.household_id == owner_user.household_id
            )
        )
        assert credential is not None
        assert credential.encrypted_value != api_key
        assert api_key not in credential.encrypted_value

    removed = client.delete("/api/v1/system/integrations/usda", headers=headers)
    assert removed.status_code == 204
    assert client.get("/api/v1/system/integrations/usda").json()["configured"] is False


def test_usda_key_rejects_whitespace_and_requires_csrf(client, owner):
    without_csrf = client.put(
        "/api/v1/system/integrations/usda",
        json={"api_key": "private-usda-key"},
    )
    assert without_csrf.status_code == 403

    invalid = client.put(
        "/api/v1/system/integrations/usda",
        json={"api_key": "not a valid key"},
        headers={"X-CSRF-Token": owner["csrf_token"]},
    )
    assert invalid.status_code == 422
