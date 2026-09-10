"""Tests for the scheduler: sync pass recomputes materialized scores."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.db import create_session_factory, seed_default_user
from app.db.models import Activity, ActivityHrSeries, Base, ComputedScore, DailyWellness
from app.ingestion import scheduler


@pytest.fixture
def sched_session(tmp_path):
    """Fresh DB with one day of wellness + one activity with HR samples."""
    factory = create_session_factory(str(tmp_path / "test.db"))
    Base.metadata.create_all(bind=factory().get_bind())
    s = factory()
    seed_default_user(s)

    day = date(2026, 8, 9)
    s.add(DailyWellness(
        user_id=1, calendar_date=day,
        resting_heart_rate=45.0, avg_stress=25.0,
        bb_at_wake=80, bb_highest=91, bb_most_recent=50,
        steps=8223, moderate_intensity_minutes=7, vigorous_intensity_minutes=10,
        avg_spo2=96.0, avg_respiration=16.0,
    ))
    act = Activity(
        user_id=1, activity_id="abc-123", activity_type="running",
        start_time_local=f"{day} 08:00:00",
        start_time_gmt=datetime(2026, 8, 9, 6, 0, tzinfo=UTC),
        duration=3600.0, max_hr=160.0,
    )
    s.add(act)
    s.flush()
    s.add(ActivityHrSeries(activity_pk=act.id, elapsed_s=60.0, hr=130.0))
    s.add(ActivityHrSeries(activity_pk=act.id, elapsed_s=120.0, hr=140.0))
    s.commit()
    return s


def test_sync_pass_computes_scores(sched_session, monkeypatch):
    """A completed sync pass must materialize computed_scores rows."""
    from app.metrics.compute import compute_recent as real_compute

    monkeypatch.setattr(scheduler, "incremental_sync", lambda days_back=3: None)  # noqa: ARG005
    # run_sync_pass imports compute_recent lazily from app.metrics.compute —
    # patch it there, injecting the test session.
    monkeypatch.setattr(
        "app.metrics.compute.compute_recent",
        lambda days=92, user_id=1, session=None: real_compute(  # noqa: ARG005
            days=days, user_id=user_id, session=sched_session
        ),
    )

    scheduler.run_sync_pass()

    rows = sched_session.execute(select(ComputedScore)).scalars().all()
    assert rows, "sync pass must materialize at least one score row"
    assert any(r.score_date == date(2026, 8, 9) for r in rows)
    assert any(r.strain is not None for r in rows)


def test_schedule_runs_first_sync_as_background_job(monkeypatch):
    """Startup must not block on the first sync pass: the sync is scheduled
    with next_run_time (background job) so Signal polling runs immediately,
    even while a long 365-day backfill is in progress."""
    calls: list[dict] = []

    class FakeScheduler:
        def __init__(self, timezone=None):
            self.timezone = timezone

        def add_job(self, fn, trigger=None, id=None, **kw):  # noqa: ARG002
            calls.append({"id": id, **kw})

        def start(self):
            pass

    class FakeSettings:
        TIMEZONE = "Europe/Amsterdam"
        SYNC_INTERVAL_MINUTES = 15
        SYNC_DAYS_BACK = 365
        SIGNAL_ENABLED = False

    monkeypatch.setattr(scheduler, "BlockingScheduler", FakeScheduler)
    monkeypatch.setattr(scheduler, "get_settings", lambda: FakeSettings())
    sync_spy = []
    monkeypatch.setattr(scheduler, "run_sync_pass", lambda: sync_spy.append(1))

    scheduler.schedule()

    sync_job = next(c for c in calls if c["id"] == "garmin-sync")
    assert sync_job["next_run_time"] is not None, "first sync must run as a scheduled job"
    assert sync_job["max_instances"] == 1
    assert not sync_spy, "sync must not run synchronously before scheduler.start()"


def test_schedule_registers_journal_and_digest_jobs_when_signal_enabled(monkeypatch):
    """Phase 5: evening journal reminder + weekly digest must be scheduled
    alongside the morning report and command poll when Signal is enabled."""
    calls: list[dict] = []

    class FakeScheduler:
        def __init__(self, timezone=None):
            self.timezone = timezone

        def add_job(self, fn, trigger=None, id=None, **kw):  # noqa: ARG002
            calls.append({"id": id, "trigger": trigger, **kw})

        def start(self):
            pass

    class FakeSettings:
        TIMEZONE = "Europe/Amsterdam"
        SYNC_INTERVAL_MINUTES = 15
        SYNC_DAYS_BACK = 3
        SIGNAL_ENABLED = True
        SIGNAL_REPORT_TIME = "07:30"
        SIGNAL_REPORT_GRACE_MINUTES = 180
        SIGNAL_REPORT_RETRY_MINUTES = 15
        SIGNAL_COMMAND_POLL_MINUTES = 5
        SIGNAL_JOURNAL_TIME = "20:30"
        SIGNAL_DIGEST_TIME = "20:00"
        SIGNAL_DIGEST_DAY = "sun"

    monkeypatch.setattr(scheduler, "BlockingScheduler", FakeScheduler)
    monkeypatch.setattr(scheduler, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(scheduler, "run_sync_pass", lambda: None)

    scheduler.schedule()

    ids = {c["id"] for c in calls}
    assert ids == {
        "garmin-sync",
        "signal-morning-report",
        "signal-command-poll",
        "signal-journal-reminder",
        "signal-weekly-digest",
    }


def test_morning_report_retries_across_the_grace_window(monkeypatch):
    """The report job must re-fire while sleep is pending, not once at 07:30.

    With report 07:30 and a 180-min grace, ticks must cover 07:30–10:30 so a
    late Garmin sleep sync is still picked up the same morning.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    calls: list[dict] = []

    class FakeScheduler:
        def __init__(self, timezone=None):
            self.timezone = timezone

        def add_job(self, fn, trigger=None, id=None, **kw):  # noqa: ARG002
            calls.append({"id": id, "trigger": trigger, **kw})

        def start(self):
            pass

    class FakeSettings:
        TIMEZONE = "Europe/Amsterdam"
        SYNC_INTERVAL_MINUTES = 15
        SYNC_DAYS_BACK = 3
        SIGNAL_ENABLED = True
        SIGNAL_REPORT_TIME = "07:30"
        SIGNAL_REPORT_GRACE_MINUTES = 180
        SIGNAL_REPORT_RETRY_MINUTES = 15
        SIGNAL_COMMAND_POLL_MINUTES = 5
        SIGNAL_JOURNAL_TIME = "20:30"
        SIGNAL_DIGEST_TIME = "20:00"
        SIGNAL_DIGEST_DAY = "sun"

    monkeypatch.setattr(scheduler, "BlockingScheduler", FakeScheduler)
    monkeypatch.setattr(scheduler, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(scheduler, "run_sync_pass", lambda: None)

    scheduler.schedule()

    trigger = next(c for c in calls if c["id"] == "signal-morning-report")["trigger"]
    tz = ZoneInfo("Europe/Amsterdam")
    cursor = datetime(2026, 9, 10, 7, 0, tzinfo=tz)
    fires = []
    for _ in range(24):
        nxt = trigger.get_next_fire_time(None, cursor)
        if nxt is None or nxt.date() > cursor.date():
            break
        fires.append(nxt)
        cursor = nxt + timedelta(seconds=1)

    times = {f.strftime("%H:%M") for f in fires}
    assert "07:30" in times  # the configured report time itself
    assert "08:30" in times  # still retrying an hour later
    assert "10:30" in times  # last tick of the 180-min grace window
    assert len(fires) > 1, "a single daily fire cannot pick up a late sleep sync"
