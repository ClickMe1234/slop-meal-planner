from __future__ import annotations

import pytest

from app.deployment import DeploymentConfigError, configure_environment


def _production_environment() -> dict[str, str]:
    return {
        "POSTGRES_HOST": "2001:db8::12",
        "POSTGRES_PORT": "55432",
        "POSTGRES_DB": "meal_planner",
        "POSTGRES_USER": "meal_planner",
        "POSTGRES_PASSWORD": "p@ss:/word?with spaces",
        "POSTGRES_SSLMODE": "require",
        "REDIS_HOST": "2001:db8::13",
        "REDIS_PORT": "6380",
        "REDIS_USERNAME": "queue user",
        "REDIS_PASSWORD": "redis:p@ss/word",
        "REDIS_TLS": "true",
        "REDIS_BROKER_DB": "2",
        "REDIS_RESULT_DB": "3",
        "MEAL_PLANNER_SECRET_KEY": "a" * 32,
        "MEAL_PLANNER_SETUP_TOKEN": "b" * 32,
        "TZ": "Europe/London",
    }


def test_friendly_fields_encode_reserved_characters_and_ipv6_hosts():
    environment = _production_environment()

    configure_environment(environment)

    assert environment["MEAL_PLANNER_DATABASE_URL"] == (
        "postgresql+psycopg://meal_planner:p%40ss%3A%2Fword%3Fwith%20spaces@"
        "[2001:db8::12]:55432/meal_planner?sslmode=require"
    )
    assert environment["CELERY_BROKER_URL"] == (
        "rediss://queue%20user:redis%3Ap%40ss%2Fword@[2001:db8::13]:6380/2"
    )
    assert environment["CELERY_RESULT_BACKEND"].endswith("/3")
    assert environment["PGHOST"] == "2001:db8::12"
    assert environment["PGSSLMODE"] == "require"
    assert environment["MEAL_PLANNER_TIMEZONE"] == "Europe/London"


def test_url_overrides_win_and_populate_backup_pg_variables():
    environment = _production_environment()
    environment.update(
        {
            "MEAL_PLANNER_DATABASE_URL": "postgresql+psycopg://override%20user:s%40fe%2Fpass@db.example:5433/override_db?sslmode=verify-full",
            "CELERY_BROKER_URL": "redis://:broker%2Fpass@redis.example:6390/5",
            "CELERY_RESULT_BACKEND": "redis://:result%2Fpass@redis.example:6390/6",
            "POSTGRES_PASSWORD": "ignored",
            "REDIS_PASSWORD": "ignored",
        }
    )

    configure_environment(environment)

    assert environment["MEAL_PLANNER_DATABASE_URL"].startswith("postgresql+psycopg://override")
    assert environment["PGHOST"] == "db.example"
    assert environment["PGPORT"] == "5433"
    assert environment["PGDATABASE"] == "override_db"
    assert environment["PGUSER"] == "override user"
    assert environment["PGPASSWORD"] == "s@fe/pass"
    assert environment["PGSSLMODE"] == "verify-full"
    assert environment["CELERY_BROKER_URL"].endswith("/5")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("POSTGRES_PORT", "0"),
        ("POSTGRES_PORT", "not-a-port"),
        ("REDIS_BROKER_DB", "abc"),
        ("REDIS_RESULT_DB", "-1"),
        ("POSTGRES_DB", "meal-planner"),
        ("MEAL_PLANNER_DATABASE_URL", "postgresql://not a url"),
        ("CELERY_BROKER_URL", "redis-sentinel://redis:26379/0"),
    ],
)
def test_invalid_connection_values_fail_without_echoing_credentials(name: str, value: str):
    environment = _production_environment()
    environment[name] = value

    with pytest.raises(DeploymentConfigError) as error:
        configure_environment(environment)

    assert "p@ss" not in str(error.value)
    assert "redis:p@ss" not in str(error.value)


def test_duplicate_friendly_redis_databases_are_rejected():
    environment = _production_environment()
    environment["REDIS_RESULT_DB"] = environment["REDIS_BROKER_DB"]

    with pytest.raises(DeploymentConfigError, match="must differ"):
        configure_environment(environment)


@pytest.mark.parametrize("name", ["MEAL_PLANNER_SECRET_KEY", "MEAL_PLANNER_SETUP_TOKEN"])
def test_placeholder_or_short_application_secrets_are_rejected(name: str):
    environment = _production_environment()
    environment[name] = "development-only-secret-change-this"

    with pytest.raises(DeploymentConfigError, match="at least 32"):
        configure_environment(environment)

