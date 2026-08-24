"""Production deployment configuration for the single-container runtime.

The application deliberately keeps its local SQLite/development defaults in
``config.py``.  This module is called by the production launcher before any
application modules are imported, so Unraid can use friendly fields without
putting credentials in shell command lines or documentation examples.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Mapping, MutableMapping
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit


class DeploymentConfigError(ValueError):
    """A safe-to-display production configuration error."""


_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_PORT_RE = re.compile(r"^[0-9]+$")
_SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
_PLACEHOLDER_SECRETS = {
    "development-only-secret-change-this",
    "development-setup-token",
    "replace-with-a-long-url-safe-random-value",
    "replace-with-a-long-random-value",
    "replace-with-a-different-long-random-value",
    "replace-with-a-one-time-long-random-value",
    "change-me",
    "changeme",
    "password",
}


@dataclass(frozen=True)
class PostgresEndpoint:
    host: str
    port: int
    database: str
    user: str
    password: str
    sslmode: str


@dataclass(frozen=True)
class RedisEndpoint:
    scheme: str
    host: str
    port: int
    username: str
    password: str
    database: int


def _value(environment: Mapping[str, str], name: str) -> str:
    return environment.get(name, "")


def _required(environment: Mapping[str, str], name: str) -> str:
    value = _value(environment, name)
    if not value:
        raise DeploymentConfigError(f"{name} is required")
    return value


def _port(environment: Mapping[str, str], name: str, default: int) -> int:
    value = _value(environment, name) or str(default)
    if not _PORT_RE.fullmatch(value):
        raise DeploymentConfigError(f"{name} must be a TCP port from 1 to 65535")
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise DeploymentConfigError(f"{name} must be a TCP port from 1 to 65535")
    return parsed


def _database_index(environment: Mapping[str, str], name: str, default: int) -> int:
    value = _value(environment, name) or str(default)
    if not _PORT_RE.fullmatch(value):
        raise DeploymentConfigError(f"{name} must be a Redis database index")
    parsed = int(value)
    if parsed < 0:
        raise DeploymentConfigError(f"{name} must be a Redis database index")
    return parsed


def _name(environment: Mapping[str, str], name: str, default: str) -> str:
    value = _value(environment, name) or default
    if not _NAME_RE.fullmatch(value):
        raise DeploymentConfigError(f"{name} may contain only letters, numbers, and underscores")
    return value


def _sslmode(environment: Mapping[str, str], name: str = "POSTGRES_SSLMODE") -> str:
    value = _value(environment, name) or "prefer"
    if value not in _SSL_MODES:
        raise DeploymentConfigError(f"{name} is not a valid PostgreSQL SSL mode")
    return value


def _format_host(host: str) -> str:
    host = host.strip()
    if not host:
        raise DeploymentConfigError("A dependency hostname or IP is required")
    if any(character.isspace() for character in host):
        raise DeploymentConfigError("Dependency hostnames and IPs may not contain spaces")
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host


def _secret(environment: Mapping[str, str], name: str) -> str:
    value = _required(environment, name)
    if len(value) < 32 or value.lower() in _PLACEHOLDER_SECRETS:
        raise DeploymentConfigError(f"{name} must be a random value of at least 32 characters")
    return value


def _safe_url_error(field: str) -> DeploymentConfigError:
    return DeploymentConfigError(f"{field} is not a valid supported connection URL")


def _auth_url(value: str, field: str, *, allow_path: bool = True) -> str:
    try:
        candidate = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
            raise ValueError
        parsed = urlsplit(candidate)
        port = parsed.port
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (not allow_path and parsed.path not in {"", "/"})
        ):
            raise ValueError
        if parsed.scheme != "https" and parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    except (TypeError, ValueError, UnicodeError):
        raise _safe_url_error(field) from None


def _validate_authentication_environment(environment: Mapping[str, str]) -> None:
    mode = (_value(environment, "MEAL_PLANNER_AUTH_MODE") or "builtin").strip()
    if mode not in {"builtin", "authentik_proxy", "authentik_oidc"}:
        raise DeploymentConfigError(
            "MEAL_PLANNER_AUTH_MODE must be builtin, authentik_proxy, or authentik_oidc"
        )
    if mode == "authentik_proxy":
        instance = _required(environment, "MEAL_PLANNER_AUTHENTIK_PROXY_INSTANCE_URL")
        _auth_url(instance, "MEAL_PLANNER_AUTHENTIK_PROXY_INSTANCE_URL")
        if not _required(environment, "MEAL_PLANNER_AUTHENTIK_PROXY_APP_SLUG").strip():
            raise DeploymentConfigError("MEAL_PLANNER_AUTHENTIK_PROXY_APP_SLUG is required")
        _secret(environment, "MEAL_PLANNER_AUTHENTIK_PROXY_SHARED_SECRET")
        logout_url = _value(environment, "MEAL_PLANNER_AUTHENTIK_PROXY_LOGOUT_URL")
        if logout_url:
            if logout_url.startswith("/"):
                if logout_url.startswith("//") or "\\" in logout_url:
                    raise DeploymentConfigError(
                        "MEAL_PLANNER_AUTHENTIK_PROXY_LOGOUT_URL must be a safe path"
                    )
            else:
                normalized_logout = _auth_url(
                    logout_url, "MEAL_PLANNER_AUTHENTIK_PROXY_LOGOUT_URL"
                )
                normalized_instance = _auth_url(
                    instance, "MEAL_PLANNER_AUTHENTIK_PROXY_INSTANCE_URL"
                )
                if (
                    urlsplit(normalized_logout).scheme,
                    urlsplit(normalized_logout).netloc,
                ) != (
                    urlsplit(normalized_instance).scheme,
                    urlsplit(normalized_instance).netloc,
                ):
                    raise DeploymentConfigError(
                        "MEAL_PLANNER_AUTHENTIK_PROXY_LOGOUT_URL must use the configured Authentik instance"
                    )
    elif mode == "authentik_oidc":
        _auth_url(
            _required(environment, "MEAL_PLANNER_PUBLIC_URL"),
            "MEAL_PLANNER_PUBLIC_URL",
            allow_path=False,
        )
        _auth_url(
            _required(environment, "MEAL_PLANNER_AUTHENTIK_OIDC_DISCOVERY_URL"),
            "MEAL_PLANNER_AUTHENTIK_OIDC_DISCOVERY_URL",
        )
        _required(environment, "MEAL_PLANNER_AUTHENTIK_OIDC_CLIENT_ID")
        _required(environment, "MEAL_PLANNER_AUTHENTIK_OIDC_CLIENT_SECRET")


def _parse_postgres_url(url: str, field: str) -> PostgresEndpoint:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError
        if parsed.fragment or not parsed.hostname or parsed.username is None or parsed.password is None:
            raise ValueError
        port = parsed.port or 5432
        database = unquote(parsed.path.lstrip("/"))
        user = unquote(parsed.username)
        password = unquote(parsed.password)
        if not database or not _NAME_RE.fullmatch(database) or not user or any(
            character in user for character in "\x00\r\n"
        ):
            raise ValueError
        query = parse_qs(parsed.query, keep_blank_values=True)
        sslmode = query.get("sslmode", ["prefer"])[-1]
        if sslmode not in _SSL_MODES:
            raise ValueError
        if not 1 <= port <= 65535:
            raise ValueError
        return PostgresEndpoint(
            host=parsed.hostname,
            port=port,
            database=database,
            user=user,
            password=password,
            sslmode=sslmode,
        )
    except (TypeError, ValueError, UnicodeError):
        raise _safe_url_error(field) from None


def _parse_redis_url(url: str, field: str) -> RedisEndpoint:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"redis", "rediss"}:
            raise ValueError
        if parsed.fragment or not parsed.hostname:
            raise ValueError
        port = parsed.port or 6379
        path = parsed.path.lstrip("/")
        if not path or not _PORT_RE.fullmatch(path):
            raise ValueError
        database = int(path)
        if database < 0 or not 1 <= port <= 65535:
            raise ValueError
        return RedisEndpoint(
            scheme=parsed.scheme,
            host=parsed.hostname,
            port=port,
            username=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=database,
        )
    except (TypeError, ValueError, UnicodeError):
        raise _safe_url_error(field) from None


def _postgres_url(endpoint: PostgresEndpoint) -> str:
    return (
        "postgresql+psycopg://"
        f"{quote(endpoint.user, safe='')}:{quote(endpoint.password, safe='')}"
        f"@{_format_host(endpoint.host)}:{endpoint.port}/{quote(endpoint.database, safe='')}"
        f"?sslmode={quote(endpoint.sslmode, safe='')}"
    )


def _redis_url(endpoint: RedisEndpoint) -> str:
    userinfo = ""
    if endpoint.username or endpoint.password:
        userinfo = quote(endpoint.username, safe="")
        if endpoint.password or not endpoint.username:
            userinfo += f":{quote(endpoint.password, safe='')}"
        userinfo += "@"
    return f"{endpoint.scheme}://{userinfo}{_format_host(endpoint.host)}:{endpoint.port}/{endpoint.database}"


def _postgres_from_environment(environment: Mapping[str, str]) -> PostgresEndpoint:
    override = _value(environment, "MEAL_PLANNER_DATABASE_URL")
    if override:
        return _parse_postgres_url(override, "MEAL_PLANNER_DATABASE_URL")
    endpoint = PostgresEndpoint(
        host=_required(environment, "POSTGRES_HOST"),
        port=_port(environment, "POSTGRES_PORT", 5432),
        database=_name(environment, "POSTGRES_DB", "meal_planner"),
        user=_name(environment, "POSTGRES_USER", "meal_planner"),
        password=_required(environment, "POSTGRES_PASSWORD"),
        sslmode=_sslmode(environment),
    )
    return endpoint


def _redis_from_environment(
    environment: Mapping[str, str], host_name: str, port_name: str, password_name: str, db_name: str
) -> RedisEndpoint:
    tls = (_value(environment, "REDIS_TLS") or "false").lower()
    if tls not in {"true", "false"}:
        raise DeploymentConfigError("REDIS_TLS must be true or false")
    return RedisEndpoint(
        scheme="rediss" if tls == "true" else "redis",
        host=_required(environment, host_name),
        port=_port(environment, port_name, 6379),
        username=_value(environment, "REDIS_USERNAME"),
        password=_value(environment, password_name),
        database=_database_index(environment, db_name, 0 if db_name.endswith("BROKER_DB") else 1),
    )


def configured_redis_urls(environment: Mapping[str, str] | None = None) -> list[str]:
    """Return the explicitly configured Redis endpoints for readiness checks."""

    source = environment if environment is not None else os.environ
    return list(dict.fromkeys(
        value for name in ("CELERY_BROKER_URL", "CELERY_RESULT_BACKEND")
        if (value := _value(source, name))
    ))


def configure_environment(
    environment: MutableMapping[str, str] | None = None,
    *,
    require_application: bool = True,
) -> MutableMapping[str, str]:
    """Validate production fields, then export the app and backup contracts.

    ``require_application=False`` is used only for standalone backup/restore
    roles. It still configures PostgreSQL fields, but does not require Redis or
    the application secrets.
    """

    target = environment if environment is not None else os.environ
    if require_application:
        _validate_authentication_environment(target)
    postgres = _postgres_from_environment(target)
    target["MEAL_PLANNER_DATABASE_URL"] = _value(target, "MEAL_PLANNER_DATABASE_URL") or _postgres_url(postgres)
    target["PGHOST"] = postgres.host
    target["PGPORT"] = str(postgres.port)
    target["PGDATABASE"] = postgres.database
    target["PGUSER"] = postgres.user
    target["PGPASSWORD"] = postgres.password
    target["PGSSLMODE"] = postgres.sslmode

    broker_override = _value(target, "CELERY_BROKER_URL")
    result_override = _value(target, "CELERY_RESULT_BACKEND")
    if require_application:
        _secret(target, "MEAL_PLANNER_SECRET_KEY")
        _secret(target, "MEAL_PLANNER_SETUP_TOKEN")
        if broker_override:
            _parse_redis_url(broker_override, "CELERY_BROKER_URL")
        else:
            broker = _redis_from_environment(
                target, "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "REDIS_BROKER_DB"
            )
            target["CELERY_BROKER_URL"] = _redis_url(broker)
        if result_override:
            result = _parse_redis_url(result_override, "CELERY_RESULT_BACKEND")
        else:
            result = _redis_from_environment(
                target, "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "REDIS_RESULT_DB"
            )
            target["CELERY_RESULT_BACKEND"] = _redis_url(result)
        broker_db = _parse_redis_url(target["CELERY_BROKER_URL"], "CELERY_BROKER_URL").database
        result_db = _parse_redis_url(target["CELERY_RESULT_BACKEND"], "CELERY_RESULT_BACKEND").database
        if broker_db == result_db:
            raise DeploymentConfigError("Redis broker and result database indexes must differ")

    target.setdefault("DATA_DIR", "/data")
    target.setdefault("BACKUP_ROOT", "/backups")
    target.setdefault("MEAL_PLANNER_TIMEZONE", target.get("TZ", "Europe/London"))
    return target


def validate_role_secrets(environment: Mapping[str, str]) -> None:
    """Validate the two application secrets without exposing their values."""

    _secret(environment, "MEAL_PLANNER_SECRET_KEY")
    _secret(environment, "MEAL_PLANNER_SETUP_TOKEN")
