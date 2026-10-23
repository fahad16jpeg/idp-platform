from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from APP_* environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    name: str = "__PROJECT_NAME__"
    version: str = "0.1.0"
    commit: str = "local"
    environment: str = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    # JSON list, e.g. APP_CORS_ORIGINS='["https://app.example.com"]'. Empty disables CORS.
    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()
