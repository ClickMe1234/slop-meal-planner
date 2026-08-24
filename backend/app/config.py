from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEAL_PLANNER_", env_file=".env", extra="ignore"
    )

    database_url: str = "sqlite:///./meal_planner.db"
    setup_token: str
    secret_key: str
    auth_mode: Literal["builtin", "authentik_proxy", "authentik_oidc"] = "builtin"
    authentik_proxy_instance_url: str = ""
    authentik_proxy_app_slug: str = ""
    authentik_proxy_shared_secret: str = ""
    authentik_proxy_logout_url: str = "/outpost.goauthentik.io/sign_out"
    public_url: str = ""
    authentik_oidc_discovery_url: str = ""
    authentik_oidc_client_id: str = ""
    authentik_oidc_client_secret: str = ""
    # Keep this as a comma-separated environment value in deploy/.env.  NoDecode
    # prevents pydantic-settings from trying JSON first; the validator below then
    # handles both the documented comma form and direct Python-list values.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    cookie_secure: bool = False
    session_days: int = 30
    login_rate_window_seconds: int = Field(default=300, ge=30, le=3600)
    login_rate_limit_per_source: int = Field(default=30, ge=3, le=1000)
    login_rate_limit_per_account: int = Field(default=10, ge=3, le=100)
    max_request_body_bytes: int = Field(default=1_048_576, ge=65_536, le=10_485_760)
    public_api_docs: bool = False
    hsts_enabled: bool = False
    timezone: str = "Europe/London"
    usda_api_key: str = ""
    remote_food_search_enabled: bool = True
    open_food_facts_enabled: bool = True
    open_food_facts_user_agent: str = (
        "SlopMealPlanner/1.4.0 (https://github.com/ClickMe1234/slop-meal-planner)"
    )
    open_food_facts_timeout_seconds: float = 10.0

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value

    @field_validator(
        "authentik_proxy_instance_url",
        "public_url",
        "authentik_oidc_discovery_url",
        mode="before",
    )
    @classmethod
    def normalize_external_url_fields(cls, value: object) -> object:
        if value is None:
            return ""
        if not isinstance(value, str):
            return value
        return _normalize_external_url(value)

    @field_validator("authentik_proxy_app_slug", "authentik_oidc_client_id")
    @classmethod
    def normalize_external_identifiers(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_authentication_configuration(self) -> "Settings":
        if self.auth_mode == "authentik_proxy":
            _require_value(self.authentik_proxy_instance_url, "authentik_proxy_instance_url")
            _require_value(self.authentik_proxy_app_slug, "authentik_proxy_app_slug")
            if len(self.authentik_proxy_shared_secret) < 32:
                raise ValueError(
                    "authentik_proxy_shared_secret must be at least 32 characters in proxy mode"
                )
            self.authentik_proxy_logout_url = _normalize_logout_url(
                self.authentik_proxy_logout_url,
                self.authentik_proxy_instance_url,
            )
        elif self.auth_mode == "authentik_oidc":
            _require_value(self.public_url, "public_url")
            if urlsplit(self.public_url).path not in {"", "/"}:
                raise ValueError("public_url must be an origin without a path")
            _require_value(self.authentik_oidc_discovery_url, "authentik_oidc_discovery_url")
            _require_value(self.authentik_oidc_client_id, "authentik_oidc_client_id")
            _require_value(self.authentik_oidc_client_secret, "authentik_oidc_client_secret")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


_LOCALHOST_NAMES = {"localhost", "127.0.0.1", "::1"}


def _require_value(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} is required for the active authentication mode")
    return value


def _normalize_external_url(value: str) -> str:
    """Normalize a provider URL while rejecting ambiguous or credentialed URLs."""

    candidate = value.strip()
    if not candidate:
        return ""
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        raise ValueError("external URLs must not contain control characters")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("external URLs must be valid absolute URLs") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("external URLs must use http or https and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("external URLs must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("external URLs must not contain a query or fragment")
    if parsed.scheme != "https" and parsed.hostname.lower() not in _LOCALHOST_NAMES:
        raise ValueError("external URLs must use HTTPS except for localhost development URLs")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("external URL ports must be between 1 and 65535")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _normalize_logout_url(value: str, instance_url: str) -> str:
    candidate = value.strip()
    if not candidate:
        return "/outpost.goauthentik.io/sign_out"
    if candidate.startswith("/"):
        if (
            candidate.startswith("//")
            or "\\" in candidate
            or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
        ):
            raise ValueError("authentik_proxy_logout_url must be a safe path or absolute URL")
        return candidate
    normalized = _normalize_external_url(candidate)
    instance = urlsplit(instance_url)
    logout = urlsplit(normalized)
    if (logout.scheme, logout.netloc) != (instance.scheme, instance.netloc):
        raise ValueError("authentik_proxy_logout_url must use the configured Authentik instance")
    return normalized
