from fastapi.testclient import TestClient

from app.routes import discovery_routes


def _csrf(owner: dict) -> dict[str, str]:
    return {"X-CSRF-Token": owner["csrf_token"]}


def test_recipe_urls_reject_active_content_and_credentials(client, owner):
    for value in (
        "javascript:window.opener.location='/settings'",
        "https://user:password@example.com/recipe",
        "data:text/html,unsafe",
    ):
        response = client.post(
            "/api/v1/recipes",
            headers=_csrf(owner),
            json={"title": "Unsafe", "source_type": "url", "source_url": value},
        )
        assert response.status_code == 422


def test_request_body_limit_and_security_headers(client):
    response = client.post(
        "/api/v1/auth/login",
        content=b"x" * 1_048_577,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "REQUEST_TOO_LARGE"

    health = client.get("/api/v1/health/live")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
    assert client.get("/api/docs").status_code == 404


def test_login_is_rate_limited_by_account(client, owner):
    for _ in range(10):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "missing-user", "password": "not-the-password"},
        )
        assert response.status_code == 401
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "missing-user", "password": "not-the-password"},
    )
    assert response.status_code == 429
    assert response.json()["code"] == "LOGIN_RATE_LIMITED"


def test_password_change_revokes_other_sessions(client, owner):
    with TestClient(client.app) as second_browser:
        login = second_browser.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": "correct-horse-battery-staple"},
        )
        assert login.status_code == 200
        changed = client.post(
            "/api/v1/auth/change-password",
            headers=_csrf(owner),
            json={
                "current_password": "correct-horse-battery-staple",
                "new_password": "another-correct-horse-battery-staple",
            },
        )
        assert changed.status_code == 204
        assert second_browser.get("/api/v1/auth/me").status_code == 401


def test_recipe_images_are_returned_through_authenticated_proxy(client, owner, monkeypatch):
    class FakeImageFetcher:
        async def fetch_bytes(self, url, *, allowed_content_types):
            assert url == "https://images.example/recipe.png"
            assert "image/png" in allowed_content_types
            return b"\x89PNG\r\n\x1a\nproxy-test", "image/png"

        async def aclose(self):
            return None

    monkeypatch.setattr(discovery_routes, "_image_fetcher", FakeImageFetcher())
    response = client.get(
        "/api/v1/recipe-discovery/image",
        params={"url": "https://images.example/recipe.png"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"\x89PNG")
