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

    # LLM (Phase 6) — private OpenAI-compatible endpoint only; explicit opt-in
    # even when BASE_URL is set, matching the SIGNAL_ENABLED pattern (never
    # call an external endpoint unless the user turns it on).
    LLM_ENABLED: bool = False
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_MODEL: str = "gpt-4o"
    LLM_MAX_TOKENS: int = 500
    LLM_TEMPERATURE: float = 0.3
    # Trailing window of computed_scores/journal fed to the coach as context
    LLM_CONTEXT_WINDOW_DAYS: int = 7
    # Append a short LLM commentary line to the Signal morning briefing
    LLM_MORNING_COMMENTARY: bool = True

    # Signal Messenger (libs/signal_messenger)
    SIGNAL_CLI_API_URL: str = "http://localhost:8080"
    SIGNAL_CLI_TOKEN: str | None = None
    # Phase 4: flip on once the number is provisioned (see ROADMAP)
    SIGNAL_ENABLED: bool = False
    SIGNAL_ACCOUNT: str | None = None  # the number registered in signal-cli
    SIGNAL_RECIPIENT: str | None = None  # number that receives reports/commands
    SIGNAL_REPORT_TIME: str = "07:30"  # morning briefing (local, Europe/Amsterdam)
    SIGNAL_COMMAND_POLL_MINUTES: int = 5
    SIGNAL_JOURNAL_TIME: str = "20:30"  # evening journal reminder
    SIGNAL_DIGEST_TIME: str = "20:00"  # weekly insights digest
    SIGNAL_DIGEST_DAY: str = "sun"  # APScheduler CronTrigger day_of_week (mon..sun)

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

    # ── Journal & insights (Phase 5) ──────────────────────────────────────
    # Gated correlation engine: a factor needs >= this many days in BOTH the
    # exposed and baseline groups (after joining with an outcome score)
    # before an insight is reported at all — never report below threshold.
    JOURNAL_INSIGHT_MIN_SAMPLES: int = 5
    JOURNAL_INSIGHT_WINDOW_DAYS: int = 90
    # The Signal evening reminder asks only this many factors per day and
    # rotates through the registry, so the message stays short. The web form
    # always shows all factors.
    JOURNAL_PROMPT_FACTORS_PER_DAY: int = 3
    # Public base URL of the dashboard, used to link the full journal form
    # from Signal messages. Empty = no link shown (e.g. LAN-only setups that
    # do not want a possibly-wrong URL in the message).
    DASHBOARD_URL: str = ""
    # A journal entry logged for day D describes what happened during D
    # (typically logged in the evening); the behavioral effect shows up in
    # the *next* morning's recovery/sleep (the night from D to D+1).
    JOURNAL_OUTCOME_OFFSET_DAYS: int = 1
    # Insights page: cap the number of cards shown (the rest stay computable
    # but off-screen) and the number of fresh LLM interpretations generated
    # per page load (cached afterwards — see coach/interpretation.py).
    INSIGHTS_MAX_DISPLAY: int = 8
    INSIGHTS_LLM_MAX_PER_LOAD: int = 3

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
