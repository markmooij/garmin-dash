"""SQLAlchemy models — Garmin Dash schema v1.

Design rules (ROADMAP.md):
- Every table carries `user_id` (single-user now, multi-user ready).
- Idempotency: unique constraints on (user_id, source_id) enable ON CONFLICT upserts.
- Timestamps: store GMT (UTC) instants; keep device-local strings alongside for display.
- Raw API payloads snapshotted in `raw_payloads` for debuggability + golden tests.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


def utcnow() -> datetime:
    """Current time as timezone-aware UTC."""
    return datetime.now(UTC)


class User(Base):
    """A user profile. Single row for now; engine is multi-user capable."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Me")
    # Profile params consumed by the metrics engine (age, max_hr, rhr, sport mix…)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyWellness(Base):
    """Per-day summary from Garmin's user_summary endpoint.

    One row per (user, calendar_date). Contains RHR, stress, SpO2, respiration,
    Body Battery extremes, intensity minutes, steps, calories.
    """

    __tablename__ = "daily_wellness"
    __table_args__ = (UniqueConstraint("user_id", "calendar_date", name="uq_wellness_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), default=1)

    calendar_date: Mapped[date] = mapped_column(Date, index=True)
    # RHR
    resting_heart_rate: Mapped[float | None] = mapped_column(Float)
    last_7d_avg_rhr: Mapped[float | None] = mapped_column(Float)
    # Heart rate range
    min_heart_rate: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    # Stress
    avg_stress: Mapped[float | None] = mapped_column(Float)
    max_stress: Mapped[int | None] = mapped_column(Integer)
    stress_duration: Mapped[dict | None] = mapped_column(JSON)  # low/med/high/rest/activity
    stress_qualifier: Mapped[str | None] = mapped_column(String(32))
    # SpO2
    avg_spo2: Mapped[float | None] = mapped_column(Float)
    lowest_spo2: Mapped[float | None] = mapped_column(Float)
    # Respiration
    avg_respiration: Mapped[float | None] = mapped_column(Float)
    # Body Battery summary
    bb_charged: Mapped[int | None] = mapped_column(Integer)
    bb_drained: Mapped[int | None] = mapped_column(Integer)
    bb_highest: Mapped[int | None] = mapped_column(Integer)
    bb_lowest: Mapped[int | None] = mapped_column(Integer)
    bb_most_recent: Mapped[int | None] = mapped_column(Integer)
    bb_at_wake: Mapped[int | None] = mapped_column(Integer)
    # Activity / intensity
    moderate_intensity_minutes: Mapped[int | None] = mapped_column(Integer)
    vigorous_intensity_minutes: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[int | None] = mapped_column(Integer)
    calories: Mapped[int | None] = mapped_column(Integer)
    floors: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SleepSession(Base):
    """One night of sleep from Garmin's sleep_data endpoint.

    Bucketed by session (sleepStart/sleepEnd), stored as UTC instants; the
    local start/end strings are kept for display in the device's timezone.
    """

    __tablename__ = "sleep_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "sleep_start_gmt", name="uq_sleep_user_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), default=1)

    calendar_date: Mapped[date] = mapped_column(Date, index=True)  # Garmin's day key
    sleep_start_gmt: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sleep_end_gmt: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sleep_start_local: Mapped[str | None] = mapped_column(String(40))
    sleep_end_local: Mapped[str | None] = mapped_column(String(40))

    # Durations (seconds)
    sleep_seconds: Mapped[int | None] = mapped_column(BigInteger)
    deep_seconds: Mapped[int | None] = mapped_column(BigInteger)
    light_seconds: Mapped[int | None] = mapped_column(BigInteger)
    rem_seconds: Mapped[int | None] = mapped_column(BigInteger)
    awake_seconds: Mapped[int | None] = mapped_column(BigInteger)
    unmeasurable_seconds: Mapped[int | None] = mapped_column(BigInteger)

    # Scores & quality
    sleep_score: Mapped[int | None] = mapped_column(Integer)
    sleep_qualifier: Mapped[str | None] = mapped_column(String(32))
    awake_count: Mapped[int | None] = mapped_column(Integer)
    avg_sleep_stress: Mapped[float | None] = mapped_column(Float)

    # Overnight vitals
    avg_spo2: Mapped[float | None] = mapped_column(Float)
    lowest_spo2: Mapped[float | None] = mapped_column(Float)
    avg_respiration: Mapped[float | None] = mapped_column(Float)
    resting_heart_rate: Mapped[int | None] = mapped_column(Integer)
    body_battery_change: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Activity(Base):
    """One workout from Garmin's activities endpoint.

    HR zone minutes (hr_time_in_zone_1..5) come straight from Garmin —
    these are Edwards zone-minutes and the primary strain input.
    """

    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("user_id", "activity_id", name="uq_activity_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), default=1)

    activity_id: Mapped[int] = mapped_column(BigInteger, index=True)
    activity_name: Mapped[str | None] = mapped_column(String(200))
    activity_type: Mapped[str] = mapped_column(String(64), index=True)  # typeKey, e.g. strength_training
    event_type: Mapped[str | None] = mapped_column(String(64))

    start_time_gmt: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    start_time_local: Mapped[str | None] = mapped_column(String(40))
    timezone_id: Mapped[str | None] = mapped_column(String(64))

    duration: Mapped[float | None] = mapped_column(Float)  # seconds
    elapsed_duration: Mapped[float | None] = mapped_column(Float)
    moving_duration: Mapped[float | None] = mapped_column(Float)

    distance_m: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[int | None] = mapped_column(Integer)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)

    hr_time_in_zone_1: Mapped[float | None] = mapped_column(Float)
    hr_time_in_zone_2: Mapped[float | None] = mapped_column(Float)
    hr_time_in_zone_3: Mapped[float | None] = mapped_column(Float)
    hr_time_in_zone_4: Mapped[float | None] = mapped_column(Float)
    hr_time_in_zone_5: Mapped[float | None] = mapped_column(Float)

    aerobic_training_effect: Mapped[float | None] = mapped_column(Float)
    anaerobic_training_effect: Mapped[float | None] = mapped_column(Float)
    difference_body_battery: Mapped[int | None] = mapped_column(Integer)

    # FIT file (downloaded, parsed into activity_hr_series)
    fit_file_path: Mapped[str | None] = mapped_column(String(300))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ActivityHrSeries(Base):
    """Intra-activity HR/pace samples parsed from the FIT file."""

    __tablename__ = "activity_hr_series"
    __table_args__ = (
        UniqueConstraint("activity_pk", "elapsed_s", name="uq_hr_series_activity_elapsed"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_pk: Mapped[int] = mapped_column(
        ForeignKey("activities.id", name="fk_hr_series_activity"), index=True
    )
    elapsed_s: Mapped[int] = mapped_column(Integer)
    hr: Mapped[int | None] = mapped_column(Integer)
    speed_mps: Mapped[float | None] = mapped_column(Float)
    cadence: Mapped[int | None] = mapped_column(Integer)


class IntradaySeries(Base):
    """1-minute resolution time series: stress, HR, Body Battery.

    kind ∈ {"stress", "body_battery", "heart_rate"}.
    """

    __tablename__ = "intraday_series"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "ts_gmt", name="uq_intraday_user_kind_ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), default=1)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    ts_gmt: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[float] = mapped_column(Float)


class JournalEntry(Base):
    """Behavioral journal responses (Phase 5)."""

    __tablename__ = "journal_entries"
    __table_args__ = (UniqueConstraint("user_id", "entry_date", name="uq_journal_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), default=1)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    responses: Mapped[dict] = mapped_column(JSON)  # {"workout_type": ..., "alcohol_drinks": ...}
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComputedScore(Base):
    """Materialized daily metric scores (Phase 2)."""

    __tablename__ = "computed_scores"
    __table_args__ = (UniqueConstraint("user_id", "score_date", name="uq_scores_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), default=1)
    score_date: Mapped[date] = mapped_column(Date, index=True)

    recovery_score: Mapped[float | None] = mapped_column(Float)  # 0-100
    recovery_band: Mapped[str | None] = mapped_column(String(16))  # red/yellow/green
    strain: Mapped[float | None] = mapped_column(Float)  # 0-21
    raw_load_trimp: Mapped[float | None] = mapped_column(Float)
    raw_load_edwards: Mapped[float | None] = mapped_column(Float)
    atl: Mapped[float | None] = mapped_column(Float)
    ctl: Mapped[float | None] = mapped_column(Float)
    tsb: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DeviceMetrics(Base):
    """Garmin-native device-level metrics (VO2max, fitness age) per date.

    Garmin only exposes the *current* VO2max value; each sync pass stores a
    snapshot under the sync date, giving a trend of what Garmin reported.
    """

    __tablename__ = "device_metrics"
    __table_args__ = (UniqueConstraint("user_id", "metric_date", name="uq_metrics_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), default=1)
    metric_date: Mapped[date] = mapped_column(Date, index=True)

    vo2max: Mapped[float | None] = mapped_column(Float)
    vo2max_precise: Mapped[float | None] = mapped_column(Float)
    fitness_age: Mapped[int | None] = mapped_column(Integer)
    max_met_category: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RawPayload(Base):
    """Snapshot of every raw API response (debuggability, re-derivation)."""

    __tablename__ = "raw_payloads"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)  # date or activity id
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SyncState(Base):
    """Per-stream sync watermark: what has been synced and when."""

    __tablename__ = "sync_state"
    __table_args__ = (UniqueConstraint("user_id", "stream", name="uq_sync_user_stream"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), default=1)
    stream: Mapped[str] = mapped_column(String(64))
    last_date: Mapped[date | None] = mapped_column(Date)
    last_sync_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    error: Mapped[str | None] = mapped_column(Text)
