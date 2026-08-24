import pytest

from app.config import Settings


def test_allowed_hosts_accepts_documented_comma_separated_environment_value(monkeypatch):
    monkeypatch.setenv(
        "MEAL_PLANNER_ALLOWED_HOSTS", "localhost, 127.0.0.1, meal-planner"
    )

    settings = Settings()

    assert settings.allowed_hosts == ["localhost", "127.0.0.1", "meal-planner"]


def test_builtin_mode_remains_the_default():
    settings = Settings()

    assert settings.auth_mode == "builtin"


def test_proxy_mode_requires_only_its_active_settings():
    with pytest.raises(ValueError, match="authentik_proxy_instance_url"):
        Settings(
            auth_mode="authentik_proxy",
            setup_token="setup-token",
            secret_key="secret-key-that-is-long-enough-for-tests",
        )

    settings = Settings(
        auth_mode="authentik_proxy",
        setup_token="setup-token",
        secret_key="secret-key-that-is-long-enough-for-tests",
        authentik_proxy_instance_url="https://auth.example.com/",
        authentik_proxy_app_slug="slop",
        authentik_proxy_shared_secret="p" * 32,
    )
    assert settings.authentik_proxy_instance_url == "https://auth.example.com"


def test_oidc_mode_rejects_public_paths_and_accepts_localhost_http():
    with pytest.raises(ValueError, match="public_url"):
        Settings(
            auth_mode="authentik_oidc",
            setup_token="setup-token",
            secret_key="secret-key-that-is-long-enough-for-tests",
            public_url="https://slop.example.com/app",
            authentik_oidc_discovery_url="https://auth.example.com/.well-known/openid-configuration",
            authentik_oidc_client_id="slop-client",
            authentik_oidc_client_secret="client-secret",
        )

    settings = Settings(
        auth_mode="authentik_oidc",
        setup_token="setup-token",
        secret_key="secret-key-that-is-long-enough-for-tests",
        public_url="http://localhost:8000/",
        authentik_oidc_discovery_url="http://localhost:9000/.well-known/openid-configuration",
        authentik_oidc_client_id="slop-client",
        authentik_oidc_client_secret="client-secret",
    )
    assert settings.public_url == "http://localhost:8000"


def test_proxy_absolute_logout_must_remain_on_authentik_origin():
    with pytest.raises(ValueError, match="configured Authentik instance"):
        Settings(
            auth_mode="authentik_proxy",
            setup_token="setup-token",
            secret_key="secret-key-that-is-long-enough-for-tests",
            authentik_proxy_instance_url="https://auth.example.com",
            authentik_proxy_app_slug="slop",
            authentik_proxy_shared_secret="p" * 32,
            authentik_proxy_logout_url="https://auth.example.com.evil.test/sign_out",
        )
