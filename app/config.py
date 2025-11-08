from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings



class Settings(BaseSettings):
    """Application runtime configuration."""

    bot_token: str = Field(..., env="RASID_BOT_TOKEN")
    database_url: str = Field(..., env="RASID_DATABASE_URL")

    redis_url: str | None = Field(None, env="RASID_REDIS_URL")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        "INFO", env="RASID_LOG_LEVEL"
    )
    media_root: Path = Field(Path("media/cards"), env="RASID_MEDIA_ROOT")
    timezone: str = Field("Asia/Tehran", env="RASID_TIMEZONE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @field_validator("media_root", mode="before")
    def resolve_media_root(cls, value: str | Path) -> Path:
        path = Path(value)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""

    return Settings()
