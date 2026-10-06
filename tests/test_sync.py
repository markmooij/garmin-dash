"""Tests for the ingestion sync worker — fake adapter, real DB."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.db.models import (
    Activity,
    DailyWellness,
    IntradaySeries,
    RawPayload,
    SleepSession,
    SyncState,
)
from app.ingestion.sync import sync_activities, sync_day, sync_intraday, sync_sleep, sync_wellness


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

    def get_max_metrics(self, cdate):
        self.calls.append(f"max_metrics:{cdate}")
        return _load("max_metrics.json")

    def download_activity_fit(self, activity_id):  # noqa: ARG002
        return b"not-a-real-fit"


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
    # Raw payload snapshot is upserted on (endpoint, key): refetching the same
    # day refreshes the snapshot rather than appending a second copy. This is
    # what kept raw_payloads from growing ~88x its useful size.
    assert session.query(RawPayload).count() == 1
    assert session.query(RawPayload).filter_by(endpoint="user_summary").count() == 1


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


def test_intraday_skips_none_body_battery_values(session):
    """Garmin emits [ts, None] placeholders for a day with no data yet (e.g.
    today before the watch syncs); sync_intraday must skip them instead of
    crashing on float(None)."""
    class NoneBodyBatteryAdapter(FakeAdapter):
        def get_stress_data(self, cdate):  # noqa: ARG002
            self.calls.append(f"stress_data:{cdate}")
            return {}

        def get_heart_rates(self, cdate):  # noqa: ARG002
            self.calls.append(f"heart_rates:{cdate}")
            return {}

        def get_body_battery(self, start, end):
            self.calls.append(f"body_battery:{start}:{end}")
            return [{"bodyBatteryValuesArray": [
                [1789257600001, None],
                [1789257600002, None],
                [1789257600003, 55],
            ]}]

    day = date(2026, 9, 13)
    adapter = NoneBodyBatteryAdapter("2026-09-13")
    sync_intraday(session, adapter, day)
    session.commit()

    bb = session.query(IntradaySeries).filter_by(kind="body_battery").all()
    assert len(bb) == 1
    assert bb[0].value == 55.0
    # no crash recorded for the stream
    errs = [
        s.error for s in session.query(SyncState).all()
        if s.stream == "intraday_body_battery"
    ]
    assert all(e is None for e in errs)


# ---------------------------------------------------------------------------
# raw_payloads: upsert semantics + retention (no fixtures — these must always
# run, since they guard the table that once grew to 3.9 GB)
# ---------------------------------------------------------------------------


def test_save_raw_upserts_instead_of_appending(session):
    """Same (endpoint, key) twice = one row, holding the *latest* payload.

    Regression guard: _save_raw used to session.add() unconditionally, so each
    15-minute sync pass over the catch-up window re-inserted every payload.
    """
    from app.ingestion.sync import _save_raw

    _save_raw(session, "sleep_data", "2026-08-09", {"sleepScore": 70})
    session.commit()
    _save_raw(session, "sleep_data", "2026-08-09", {"sleepScore": 85})
    session.commit()

    rows = session.query(RawPayload).filter_by(endpoint="sleep_data", key="2026-08-09").all()
    assert len(rows) == 1
    assert rows[0].payload == {"sleepScore": 85}


def test_save_raw_keeps_distinct_keys_apart(session):
    from app.ingestion.sync import _save_raw

    _save_raw(session, "stress_data", "2026-08-09", {"v": 1})
    _save_raw(session, "stress_data", "2026-08-10", {"v": 2})
    _save_raw(session, "heart_rates", "2026-08-09", {"v": 3})
    session.commit()

    assert session.query(RawPayload).count() == 3


def test_save_raw_is_a_noop_when_disabled(session, monkeypatch):
    """Nothing reads raw_payloads, so the switch must actually suppress writes."""
    from types import SimpleNamespace

    from app import ingestion

    monkeypatch.setattr(
        ingestion.sync, "get_settings", lambda: SimpleNamespace(RAW_PAYLOADS_ENABLED=False)
    )
    ingestion.sync._save_raw(session, "sleep_data", "2026-08-09", {"sleepScore": 70})
    session.commit()
    assert session.query(RawPayload).count() == 0


def test_purge_raw_payloads_removes_only_stale_rows(session, monkeypatch):
    """Retention keys off fetched_at: rows still being refetched survive."""
    from types import SimpleNamespace

    from app import ingestion
    from app.ingestion.sync import _save_raw, purge_raw_payloads

    _save_raw(session, "sleep_data", "2026-08-09", {"v": 1})
    _save_raw(session, "sleep_data", "2026-08-10", {"v": 2})
    session.commit()

    # Age one row beyond the window by pushing its fetched_at back.
    old = (
        session.query(RawPayload)
        .filter_by(endpoint="sleep_data", key="2026-08-09")
        .one()
    )
    old.fetched_at = datetime.now(UTC) - timedelta(days=200)
    session.commit()

    monkeypatch.setattr(
        ingestion.sync, "get_settings", lambda: SimpleNamespace(RAW_PAYLOADS_MAX_DAYS=90)
    )
    deleted = purge_raw_payloads(session=session)

    assert deleted == 1
    remaining = [(r.key, r.payload) for r in session.query(RawPayload).all()]
    assert remaining == [("2026-08-10", {"v": 2})]


def test_purge_raw_payloads_disabled_keeps_everything(session, monkeypatch):
    from types import SimpleNamespace

    from app import ingestion
    from app.ingestion.sync import _save_raw, purge_raw_payloads

    _save_raw(session, "sleep_data", "2026-01-01", {"v": 1})
    session.commit()
    row = session.query(RawPayload).one()
    row.fetched_at = datetime.now(UTC) - timedelta(days=999)
    session.commit()

    monkeypatch.setattr(
        ingestion.sync, "get_settings", lambda: SimpleNamespace(RAW_PAYLOADS_MAX_DAYS=0)
    )
    assert purge_raw_payloads(session=session) == 0
    assert session.query(RawPayload).count() == 1
