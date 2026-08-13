"""Centralized settings with pydantic-settings + dotenv."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_MODEL: str = "gpt-4o"

    # Signal Messenger (libs/signal_messenger)
    SIGNAL_CLI_API_URL: str = "http://localhost:8080"
    SIGNAL_CLI_TOKEN: str | None = None
    # Phase 4: flip on once the number is provisioned (see ROADMAP)
    SIGNAL_ENABLED: bool = False
    SIGNAL_ACCOUNT: str | None = None  # the number registered in signal-cli
    SIGNAL_RECIPIENT: str | None = None  # number that receives reports/commands
    SIGNAL_REPORT_TIME: str = "07:30"  # morning briefing (local, Europe/Amsterdam)
    SIGNAL_COMMAND_POLL_MINUTES: int = 5

    # Garmin
    GARMINTOKENS: str | None = None

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # Ingestion scheduler
    SYNC_INTERVAL_MINUTES: str = "15"
    SYNC_DAYS_BACK: str = "3"

    # Local day boundary for intraday views and reports
    # (Garmin timestamps are stored in UTC; the UI buckets by this zone)
    TIMEZONE: str = "Europe/Amsterdam"

    # ── Metrics engine (Phase 2) ──────────────────────────────────────────
    # TRIMP normalization: session HRr = (HR - rest) / (max - rest).
    # Rest HR per-session = that day's resting_heart_rate; fallback constant.
    # Max HR: observed max across activities + buffer; fallback constant.
    HR_REST_FALLBACK: int = 48
    HR_MAX_FALLBACK: int = 190
    HR_MAX_OBSERVED_BUFFER: int = 5

    # Strain calibration: rolling-window 95th percentile of daily raw load ≈ 20
    STRAIN_WINDOW_DAYS: int = 90
    STRAIN_PERCENTILE: float = 0.95
    STRAIN_CAP: float = 21.0

    # Recovery composite weights (must sum to 1 when HRV present).
    # When HRV is missing (Venu 2), HRV weight is dropped and the rest are
    # renormalized to sum 1. Missing inputs are dropped the same way.
    RECOVERY_WEIGHTS_HRV: str = '{"hrv": 0.5, "rhr": 0.2, "sleep": 0.2, "stress": 0.1}'
    RECOVERY_BASELINE_DAYS: int = 60
    RECOVERY_MIN_BASELINE_DAYS: int = 7
    RECOVERY_BAND_GREEN: float = 66.0  # >= green
    RECOVERY_BAND_YELLOW: float = 34.0  # >= yellow, < green; below = red

    # Duration-based load for strength-like sports (load points per minute),
    # because HR undercounts strength. Configurable per sport profile.
    SPORT_LOAD_FACTORS: str = '{"strength_training": 45.0, "boxing": 25.0}'

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
