"""Centralized settings with pydantic-settings + dotenv."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """App-wide settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # General
    APP_NAME: str = "Garmin Dash"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Database
    DB_PATH: str = "data/garmin_dash.db"

    # Docker profiles
    DOCKER_PROFILE: str = "dev"  # dev | prod
    SIGNAL_API_HOST: str = "localhost"
    SIGNAL_API_PORT: int = 8080

    # LLM (Phase 6)
    LLM_BASE_URL: Optional[str] = None
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4o"

    # Signal Messenger (libs/signal_messenger)
    SIGNAL_CLI_API_URL: str = "http://localhost:8080"
    SIGNAL_CLI_TOKEN: Optional[str] = None

    # Garmin
    GARMINTOKENS: Optional[str] = None

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    @property
    def is_prod(self) -> bool:
        """Check if running in production profile."""
        return self.DOCKER_PROFILE == "prod"

    @property
    def log_path(self) -> Path:
        """Return the log directory."""
        return Path("logs")

    @property
    def data_path(self) -> Path:
        """Return the data directory."""
        return Path("data")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
