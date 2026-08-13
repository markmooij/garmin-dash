"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from app.db import create_session_factory, seed_default_user
from app.db.models import (
    Activity,
    Base,
    ComputedScore,
    DailyWellness,
    DeviceMetrics,
    IntradaySeries,
    SleepSession,
)


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@pytest.fixture
def session(tmp_path) -> Session:
    factory = create_session_factory(str(tmp_path / "test.db"))
    Base.metadata.create_all(bind=factory().get_bind())
    s = factory()
    seed_default_user(s)
    return s


@pytest.fixture
def seeded(session: Session) -> Session:
    """A session with one fully-populated day (2026-08-09)."""
    day = date(2026, 8, 9)
    session.add(DailyWellness(
        user_id=1, calendar_date=day,
        resting_heart_rate=45.0, avg_stress=25.0,
        bb_at_wake=80, bb_highest=91, bb_most_recent=50,
        steps=8223, moderate_intensity_minutes=7, vigorous_intensity_minutes=10,
        avg_spo2=96.0, avg_respiration=16.0,
    ))
    session.add(SleepSession(
        user_id=1, calendar_date=day, sleep_score=81.0,
        sleep_start_gmt=datetime(2026, 8, 8, 22, 30, tzinfo=UTC),
        sleep_end_gmt=datetime(2026, 8, 9, 7, 0, tzinfo=UTC),
        sleep_start_local="2026-08-09 00:30:00", sleep_end_local="2026-08-09 09:00:00",
        sleep_seconds=7 * 3600, deep_seconds=6060, rem_seconds=3840,
        light_seconds=5 * 3600 + 2100, awake_seconds=1440,
        avg_sleep_stress=22.0, resting_heart_rate=45,
    ))
    session.add(Activity(
        user_id=1, activity_id=999, activity_name="Kracht", activity_type="strength_training",
        start_time_gmt=datetime(2026, 8, 9, 9, 13, 46, tzinfo=UTC),
        start_time_local="2026-08-09 11:13:46", timezone_id="Europe/Amsterdam",
        duration=3600, elapsed_duration=3600, moving_duration=3600,
        avg_hr=110, max_hr=150,
        hr_time_in_zone_1=600, hr_time_in_zone_2=1200, hr_time_in_zone_3=1800,
        hr_time_in_zone_4=0, hr_time_in_zone_5=0,
        aerobic_training_effect=2.5, anaerobic_training_effect=1.2,
        difference_body_battery=-6,
    ))
    session.add(DeviceMetrics(
        user_id=1, metric_date=day, vo2max=51.0, vo2max_precise=51.3,
    ))
    session.add(ComputedScore(
        user_id=1, score_date=day,
        recovery_score=71.5, recovery_band="green",
        strain=15.25, raw_load_trimp=1707.8, raw_load_edwards=103.7,
        atl=5.4, ctl=2.5, tsb=-2.9,
        payload={
            "raw_load": 4098.9,
            "recovery": {
                "score": 71.5, "band": "green", "hrv_used": False,
                "components": {"rhr": 60.0, "sleep": 81.0, "stress": 75.0},
                "weights": {"rhr": 0.4, "sleep": 0.4, "stress": 0.2},
            },
            "breakdown": [{"activity_id": 999, "type": "strength_training",
                           "trimp": 1707.8, "edwards": 103.7, "strength_duration": 2391.1}],
        },
    ))
    for kind, vals in (
        ("heart_rate", [(1786233600 + i * 60, 70 + i % 10) for i in range(30)]),
        ("stress", [(1786233600 + i * 60, 20 + i % 5) for i in range(30)]),
        ("body_battery", [(1786233600 + i * 600, 70 + i) for i in range(5)]),
    ):
        for ts, v in vals:
            session.add(IntradaySeries(
                user_id=1, kind=kind,
                ts_gmt=datetime.fromtimestamp(ts, tz=UTC),
                value=float(v),
            ))
    session.commit()
    return session
