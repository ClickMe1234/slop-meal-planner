from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEAL_PLANNER_", env_file=".env", extra="ignore"
    )

    database_url: str = "sqlite:///./meal_planner.db"
    setup_token: str
    secret_key: str
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
        "SlopMealPlanner/1.2.0 (https://github.com/ClickMe1234/slop-meal-planner)"
    )
    open_food_facts_timeout_seconds: float = 10.0

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
