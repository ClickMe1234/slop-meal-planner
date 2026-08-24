from __future__ import annotations

import asyncio
import os
import secrets
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from sqlalchemy import select

from app.auth import hash_password
from app.config import Settings, get_settings
from app.errors import DomainError
from app.models import AuthMethod, ExternalIdentity, Household, User, UserRole, UserSession
from app.routes import auth_routes
from app.services import oidc


@pytest.fixture()
def proxy_environment():
    values = {
        "MEAL_PLANNER_AUTH_MODE": "authentik_proxy",
        "MEAL_PLANNER_AUTHENTIK_PROXY_INSTANCE_URL": "https://auth.example.com/",
        "MEAL_PLANNER_AUTHENTIK_PROXY_APP_SLUG": "slop",
        "MEAL_PLANNER_AUTHENTIK_PROXY_SHARED_SECRET": "p" * 64,
        "MEAL_PLANNER_AUTHENTIK_PROXY_LOGOUT_URL": "/outpost.goauthentik.io/sign_out",
    }
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    get_settings.cache_clear()
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()


def _seed_user(session_factory, username: str = "owner") -> str:
    with session_factory() as db:
        household = Household(name="External household", timezone="Europe/London")
        db.add(household)
        db.flush()
        user = User(
            household_id=household.id,
            username=username,
            password_hash=hash_password("unused-password-value"),
            role=UserRole.OWNER.value,
        )
        db.add(user)
        db.commit()
        return user.id


def _proxy_headers(username: str = "owner", subject: str = "auth-user-1") -> dict[str, str]:
    return {
        "X-Slop-Auth-Proxy-Secret": "p" * 64,
        "X-authentik-uid": subject,
        "X-authentik-username": username,
        "X-authentik-meta-app": "slop",
    }


@pytest.fixture()
def oidc_environment():
    values = {
        "MEAL_PLANNER_AUTH_MODE": "authentik_oidc",
        "MEAL_PLANNER_PUBLIC_URL": "https://slop.example.com",
        "MEAL_PLANNER_AUTHENTIK_OIDC_DISCOVERY_URL": "https://auth.example.com/application/o/slop/.well-known/openid-configuration",
        "MEAL_PLANNER_AUTHENTIK_OIDC_CLIENT_ID": "slop-client",
        "MEAL_PLANNER_AUTHENTIK_OIDC_CLIENT_SECRET": "client-secret",
        "MEAL_PLANNER_COOKIE_SECURE": "false",
    }
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    get_settings.cache_clear()
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()


def test_proxy_session_links_existing_user_and_requires_headers(
    proxy_environment, client, session_factory
):
    user_id = _seed_user(session_factory)

    config = client.get("/api/v1/auth/config")
    assert config.status_code == 200
    assert config.json() == {
        "mode": "authentik_proxy",
        "provider": "authentik",
        "password_login_enabled": False,
    }

    session = client.post("/api/v1/auth/proxy/session", headers=_proxy_headers())
    assert session.status_code == 200, session.text
    assert session.json()["user"]["id"] == user_id
    csrf = session.json()["csrf_token"]

    opened = client.get("/api/v1/auth/me", headers=_proxy_headers())
    assert opened.status_code == 200
    assert opened.json()["username"] == "owner"

    renamed = client.get(
        "/api/v1/auth/me",
        headers=_proxy_headers(username="renamed"),
    )
    assert renamed.status_code == 200

    missing_headers = client.get("/api/v1/auth/me")
    assert missing_headers.status_code == 401
    assert missing_headers.json()["code"] == "AUTHENTIK_PROXY_SECRET_INVALID"

    changed = client.patch(
        "/api/v1/auth/me",
        headers={**_proxy_headers(username="renamed"), "X-CSRF-Token": csrf},
        json={"measurement_system": "metric"},
    )
    assert changed.status_code == 200, changed.text

    with session_factory() as db:
        identity = db.scalar(select(ExternalIdentity))
        assert identity is not None
        assert identity.user_id == user_id
        assert identity.subject == "auth-user-1"
        assert identity.last_seen_username == "renamed"
        stored_session = db.scalar(select(UserSession))
        assert stored_session is not None
        assert stored_session.auth_method == AuthMethod.AUTHENTIK_PROXY.value


def test_external_mode_disables_password_and_collaborator_routes(proxy_environment, client):
    cases = [
        (
            "/api/v1/auth/setup",
            {
                "setup_token": "development-setup-token",
                "household_name": "Nope",
                "username": "owner",
                "password": "correct-horse-battery-staple",
            },
        ),
        (
            "/api/v1/auth/login",
            {"username": "owner", "password": "correct-horse-battery-staple"},
        ),
        (
            "/api/v1/auth/change-password",
            {"current_password": "old", "new_password": "new-password-value"},
        ),
        (
            "/api/v1/auth/users",
            {"username": "helper", "temporary_password": "temporary-password-value"},
        ),
    ]
    for path, payload in cases:
        response = client.post(path, json=payload)
        assert response.status_code == 409, (path, response.text)
        assert response.json()["code"] == "AUTH_METHOD_DISABLED"


def test_external_login_requires_an_existing_local_user(proxy_environment, client):
    response = client.post(
        "/api/v1/auth/proxy/session", headers=_proxy_headers()
    )

    assert response.status_code == 409
    assert response.json()["code"] == "AUTHENTIK_ACCOUNT_SETUP_REQUIRED"


def test_switching_auth_mode_invalidates_external_session(
    proxy_environment, client, session_factory
):
    _seed_user(session_factory)
    signed_in = client.post("/api/v1/auth/proxy/session", headers=_proxy_headers())
    assert signed_in.status_code == 200

    previous = os.environ["MEAL_PLANNER_AUTH_MODE"]
    os.environ["MEAL_PLANNER_AUTH_MODE"] = "builtin"
    get_settings.cache_clear()
    try:
        response = client.get("/api/v1/auth/me")
    finally:
        os.environ["MEAL_PLANNER_AUTH_MODE"] = previous
        get_settings.cache_clear()

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_MODE_CHANGED"
    with session_factory() as db:
        assert db.scalar(select(UserSession)) is None


def test_oidc_return_paths_and_authorization_request(monkeypatch):
    settings = Settings(
        setup_token="setup-token",
        secret_key="secret-key-that-is-long-enough-for-tests",
        auth_mode="authentik_oidc",
        public_url="https://slop.example.com/",
        authentik_oidc_discovery_url="https://auth.example.com/application/o/slop/.well-known/openid-configuration",
        authentik_oidc_client_id="slop-client",
        authentik_oidc_client_secret="client-secret",
    )
    metadata = {
        "issuer": "https://auth.example.com/application/o/slop",
        "authorization_endpoint": "https://auth.example.com/application/o/authorize",
        "token_endpoint": "https://auth.example.com/application/o/token",
        "jwks_uri": "https://auth.example.com/application/o/jwks",
    }

    async def provider_metadata(_settings):
        return metadata

    monkeypatch.setattr(oidc, "get_provider_metadata", provider_metadata)
    url, transaction = asyncio.run(oidc.authorization_url(settings, "/recipes?source=auth"))
    query = parse_qs(urlsplit(url).query)

    assert query["client_id"] == ["slop-client"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile email"]
    assert query["redirect_uri"] == [
        "https://slop.example.com/api/v1/auth/oidc/callback"
    ]
    assert query["code_challenge_method"] == ["S256"]
    assert transaction
    assert oidc.sanitize_return_path("//evil.example") == "/week"
    assert oidc.sanitize_return_path("https://evil.example") == "/week"
    assert oidc.sanitize_return_path("/api/v1/auth/logout") == "/week"
    assert oidc.sanitize_return_path("/recipes?source=auth") == "/recipes?source=auth"


def test_oidc_end_session_uses_fixed_return_and_encrypted_hint():
    settings = Settings(
        setup_token="setup-token",
        secret_key="secret-key-that-is-long-enough-for-tests",
        auth_mode="authentik_oidc",
        public_url="https://slop.example.com",
        authentik_oidc_discovery_url="https://auth.example.com/.well-known/openid-configuration",
        authentik_oidc_client_id="slop-client",
        authentik_oidc_client_secret="client-secret",
    )
    encrypted = oidc.make_transaction_cookie({"id_token": "not-used"}, settings)
    # The logout helper decrypts a stored ID token, so use its public crypto
    # helper to create the same shape a callback stores.
    from app.services.integration_credentials import encrypt_value

    redirect = oidc.end_session_url(
        settings,
        {"end_session_endpoint": "https://auth.example.com/application/o/end-session"},
        encrypt_value("signed-id-token", settings),
    )
    assert redirect is not None
    parsed = parse_qs(urlsplit(redirect).query)
    assert parsed["id_token_hint"] == ["signed-id-token"]
    assert parsed["post_logout_redirect_uri"] == [
        "https://slop.example.com/login?logged_out=1"
    ]
    assert encrypted


def test_oidc_jwt_validation_handles_sid_only_logout_and_rejects_nonce(monkeypatch):
    settings = Settings(
        setup_token="setup-token",
        secret_key="secret-key-that-is-long-enough-for-tests",
        auth_mode="authentik_oidc",
        public_url="https://slop.example.com",
        authentik_oidc_discovery_url="https://auth.example.com/.well-known/openid-configuration",
        authentik_oidc_client_id="slop-client",
        authentik_oidc_client_secret="client-secret",
    )
    metadata = {"issuer": "https://auth.example.com/application/o/slop"}
    signing_key = RSAKey.generate_key(
        parameters={"alg": "RS256", "use": "sig"}, auto_kid=True
    )
    public_key_set = KeySet.import_key_set({"keys": [signing_key.as_dict(private=False)]})

    async def jwks(_metadata, *, refresh=False):
        return public_key_set

    monkeypatch.setattr(oidc, "_get_jwks", jwks)
    now = int(time.time())
    logout_claims = {
        "iss": metadata["issuer"],
        "aud": settings.authentik_oidc_client_id,
        "iat": now,
        "exp": now + 300,
        "jti": "logout-jti",
        "sid": "provider-session-1",
        "events": {oidc.BACKCHANNEL_LOGOUT_EVENT: {}},
    }
    token = jwt.encode({"alg": "RS256"}, logout_claims, signing_key)
    validated = asyncio.run(
        oidc.validate_jwt(token, metadata, settings, require_logout_claims=True)
    )
    assert validated["sid"] == "provider-session-1"

    invalid = {**logout_claims, "nonce": "must-not-be-present"}
    invalid_token = jwt.encode({"alg": "RS256"}, invalid, signing_key)
    with pytest.raises(DomainError) as error:
        asyncio.run(
            oidc.validate_jwt(
                invalid_token, metadata, settings, require_logout_claims=True
            )
        )
    assert error.value.code == "AUTHENTIK_INVALID_CALLBACK"


def test_oidc_callback_persists_only_encrypted_logout_metadata_and_backchannel_replays(
    oidc_environment, client, session_factory, monkeypatch
):
    user_id = _seed_user(session_factory)
    settings = get_settings()
    state = secrets.token_urlsafe(24)
    transaction = oidc.make_transaction_cookie(
        {
            "state": state,
            "nonce": "callback-nonce",
            "code_verifier": "verifier",
            "issued_at": int(time.time()),
            "return_to": "/recipes?from=oidc",
        },
        settings,
    )
    metadata = {
        "issuer": "https://auth.example.com/application/o/slop",
        "end_session_endpoint": "https://auth.example.com/application/o/end-session",
    }

    async def provider_metadata(_settings):
        return metadata

    async def exchange(_settings, _metadata, *, code, code_verifier):
        assert code == "authorization-code"
        assert code_verifier == "verifier"
        return {
            "id_token": "signed-id-token",
            "access_token": "short-lived-access-token",
            "refresh_token": "must-not-be-persisted",
        }

    async def validate(token, _metadata, _settings, *, require_logout_claims=False):
        if require_logout_claims:
            assert token == "logout-token"
            return {
                "iss": metadata["issuer"],
                "aud": "slop-client",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "jti": "logout-jti",
                "sid": "provider-session-1",
                "events": {oidc.BACKCHANNEL_LOGOUT_EVENT: {}},
            }
        assert token == "signed-id-token"
        return {
            "iss": metadata["issuer"],
            "aud": "slop-client",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "sub": "oidc-user-1",
            "preferred_username": "OWNER",
            "nonce": "callback-nonce",
            "sid": "provider-session-1",
        }

    monkeypatch.setattr(auth_routes, "get_provider_metadata", provider_metadata)
    monkeypatch.setattr(auth_routes, "exchange_code", exchange)
    monkeypatch.setattr(auth_routes, "validate_jwt", validate)
    client.cookies.set(oidc.OIDC_TRANSACTION_COOKIE, transaction, path="/")

    callback = client.get(
        "/api/v1/auth/oidc/callback?code=authorization-code&state=" + state,
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert callback.headers["location"] == "/recipes?from=oidc"

    with session_factory() as db:
        identity = db.scalar(select(ExternalIdentity))
        assert identity is not None
        assert identity.user_id == user_id
        stored_session = db.scalar(select(UserSession))
        assert stored_session is not None
        assert stored_session.auth_method == AuthMethod.AUTHENTIK_OIDC.value
        assert oidc.decrypt_value(stored_session.encrypted_id_token, settings) == "signed-id-token"
        assert "short-lived-access-token" not in stored_session.encrypted_id_token
        assert "must-not-be-persisted" not in stored_session.encrypted_id_token

    first_logout = client.post(
        "/api/v1/auth/oidc/backchannel-logout", data={"logout_token": "logout-token"}
    )
    replay = client.post(
        "/api/v1/auth/oidc/backchannel-logout", data={"logout_token": "logout-token"}
    )
    assert first_logout.status_code == 204
    assert replay.status_code == 204
    with session_factory() as db:
        assert db.scalar(select(UserSession)) is None
