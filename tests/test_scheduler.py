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
