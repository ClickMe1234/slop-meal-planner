from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEAL_PLANNER_", env_file=".env", extra="ignore"
    )

    database_url: str = "sqlite:///./meal_planner.db"
    setup_token: str = "development-setup-token"
    secret_key: str = "development-only-secret-change-this"
    # Keep this as a comma-separated environment value in deploy/.env.  NoDecode
    # prevents pydantic-settings from trying JSON first; the validator below then
    # handles both the documented comma form and direct Python-list values.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    cookie_secure: bool = False
    session_days: int = 30
    timezone: str = "Europe/London"

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
