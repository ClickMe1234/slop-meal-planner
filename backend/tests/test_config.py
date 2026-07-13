from app.config import Settings


def test_allowed_hosts_accepts_documented_comma_separated_environment_value(monkeypatch):
    monkeypatch.setenv(
        "MEAL_PLANNER_ALLOWED_HOSTS", "localhost, 127.0.0.1, meal-planner"
    )

    settings = Settings()

    assert settings.allowed_hosts == ["localhost", "127.0.0.1", "meal-planner"]
