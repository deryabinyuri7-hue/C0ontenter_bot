from functools import lru_cache
from typing import Annotated

from pydantic import BeforeValidator, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def parse_ids(value: str | list[int]) -> list[int]:
    if isinstance(value, list):
        return value
    return [int(item.strip()) for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr
    database_url: str
    admin_ids: Annotated[list[int], NoDecode, BeforeValidator(parse_ids)] = Field(
        default_factory=list
    )
    welcome_credits: int = Field(default=1, ge=0)
    log_level: str = "INFO"
    kie_api_key: SecretStr | None = None
    image_model_id: str | None = None
    kie_image_task_status_path: str | None = None
    kie_poll_interval_seconds: int = Field(default=10, ge=1, le=60)
    kie_max_wait_seconds: int = Field(default=600, ge=30, le=3600)

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
