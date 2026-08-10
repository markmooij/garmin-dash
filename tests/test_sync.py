"""Tests for the ingestion sync worker — fake adapter, real DB."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from app.db import Base, create_session_factory
from app.db.models import (
    Activity,
    DailyWellness,
    IntradaySeries,
    RawPayload,
    SleepSession,
    SyncState,
)
from app.ingestion.sync import sync_activities, sync_day, sync_intraday, sync_sleep, sync_wellness


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


FIXTURES = Path("tests/fixtures/garmin")


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


class FakeAdapter:
    """Serves the captured real payloads; records which dates were asked for."""

    def __init__(self, day: str):
        self.day = day
        self.calls: list[str] = []

    def get_user_summary(self, cdate):
        self.calls.append(f"user_summary:{cdate}")
        return _load("user_summary.json")

    def get_sleep_data(self, cdate):
        self.calls.append(f"sleep_data:{cdate}")
        return _load("sleep_data.json")

    def get_stress_data(self, cdate):
        self.calls.append(f"stress_data:{cdate}")
        return _load("stress_data.json")

    def get_heart_rates(self, cdate):
        self.calls.append(f"heart_rates:{cdate}")
        return _load("heart_rates.json")

    def get_body_battery(self, start, end):
        self.calls.append(f"body_battery:{start}:{end}")
        return _load("body_battery.json")

    def get_hrv_data(self, cdate):
        self.calls.append(f"hrv:{cdate}")
        return {}

    def get_activities(self, start, limit):
        self.calls.append(f"activities:{start}:{limit}")
        return _load("activities.json")

    def get_activity_details(self, activity_id):  # noqa: ARG002
        return {}

    def download_activity_fit(self, activity_id):  # noqa: ARG002
        return b"not-a-real-fit"


@pytest.fixture
def session(tmp_path) -> Session:
    factory = create_session_factory(str(tmp_path / "test.db"))
    Base.metadata.create_all(bind=factory().get_bind())
    s = factory()
    from app.db import seed_default_user

    seed_default_user(s)
    return s


@pytest.fixture
def adapter():
    return FakeAdapter("2026-08-09")


def test_wellness_upsert_is_idempotent(session, adapter):
    """Syncing the same day twice yields exactly one wellness row."""
    day = date(2026, 8, 9)
    sync_wellness(session, adapter, day)
    sync_wellness(session, adapter, day)
    session.commit()

    rows = session.query(DailyWellness).all()
    assert len(rows) == 1
    w = rows[0]
    assert w.resting_heart_rate == 45
    assert w.calendar_date == day
    assert w.steps is not None
    # raw payload snapshot stored once per fetch (2 fetches → 2 snapshots is fine)
    assert session.query(RawPayload).count() == 2


def test_sleep_parses_stages_and_scores(session, adapter):
    day = date(2026, 8, 9)
    sync_sleep(session, adapter, day)
    session.commit()

    rows = session.query(SleepSession).all()
    assert len(rows) == 1
    s = rows[0]
    assert s.sleep_score == 81
    assert s.sleep_qualifier == "GOOD"
    assert s.deep_seconds is not None
    assert s.rem_seconds is not None
    # session bucketing: start < end
    assert s.sleep_start_gmt < s.sleep_end_gmt
    assert s.sleep_start_local is not None


def test_intraday_bulk_load(session, adapter):
    day = date(2026, 8, 9)
    sync_intraday(session, adapter, day)
    session.commit()

    stress = session.query(IntradaySeries).filter_by(kind="stress").count()
    hr = session.query(IntradaySeries).filter_by(kind="heart_rate").count()
    bb = session.query(IntradaySeries).filter_by(kind="body_battery").count()
    assert stress > 100
    assert hr > 100
    assert bb > 0  # fixture has sparse body-battery samples
    # idempotent: second run does not duplicate
    sync_intraday(session, adapter, day)
    session.commit()
    assert session.query(IntradaySeries).filter_by(kind="stress").count() == stress


def test_sync_day_marks_watermarks(session, adapter):
    day = date(2026, 8, 9)
    sync_day(day, adapter, session)
    session.commit()

    streams = {s.stream for s in session.query(SyncState).all()}
    assert {"daily_wellness", "sleep"} <= streams
    assert any(s.stream == "daily_wellness" and s.last_date == day for s in session.query(SyncState))


def test_activities_upsert(session, adapter):
    sync_activities(session, adapter, limit=20, fetch_fit=False)
    session.commit()
    n = session.query(Activity).count()
    assert n == 20
    # strength training present
    types = {a.activity_type for a in session.query(Activity).all()}
    assert "strength_training" in types
    # idempotent
    sync_activities(session, adapter, limit=20, fetch_fit=False)
    session.commit()
    assert session.query(Activity).count() == n


def test_missing_day_does_not_raise(session, tmp_path):  # noqa: ARG001
    """A 404-ish empty day is tolerated and recorded, not fatal."""
    class EmptyAdapter(FakeAdapter):
        def get_user_summary(self, cdate):  # noqa: ARG002
            self.calls.append(f"user_summary:{cdate}")
            return {}

        def get_sleep_data(self, cdate):  # noqa: ARG002
            self.calls.append(f"sleep_data:{cdate}")
            return {}

        def get_stress_data(self, cdate):  # noqa: ARG002
            raise RuntimeError("boom")

    day = date(2026, 8, 9)
    adapter = EmptyAdapter("2026-08-09")
    sync_day(day, adapter, session)
    session.commit()
    # wellness row absent (empty payload), sleep absent, error recorded for stress
    assert session.query(DailyWellness).count() == 0
    errs = [s.error for s in session.query(SyncState).all() if s.error]
    assert any("boom" in (e or "") for e in errs)
