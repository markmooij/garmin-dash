"""Phase 5: journal entries + gated correlation insight engine."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from app.db.models import ComputedScore
from app.journal.entries import entries_in_range, get_entry, upsert_entry, upsert_response
from app.journal.insights import compute_all_insights, compute_insight
from app.journal.schema import FACTORS_BY_KEY, parse_bool


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── schema ────────────────────────────────────────────────────────────

def test_parse_bool():
    assert parse_bool("j") is True
    assert parse_bool("Ja") is True
    assert parse_bool("y") is True
    assert parse_bool("1") is True
    assert parse_bool("n") is False
    assert parse_bool("nee") is False
    assert parse_bool("0") is False
    assert parse_bool("huh") is None


def test_factors_registry_has_known_keys():
    assert "alcohol" in FACTORS_BY_KEY
    assert FACTORS_BY_KEY["alcohol"].kind == "count"
    assert FACTORS_BY_KEY["stress_hoog"].kind == "bool"


# ── entries.py ────────────────────────────────────────────────────────

def test_upsert_response_creates_and_merges(session: Session):
    day = date(2026, 8, 1)
    upsert_response(session, day, "alcohol", 2.0)
    entry = get_entry(session, day)
    assert entry is not None
    assert entry.responses == {"alcohol": 2.0}

    # second call merges rather than replacing
    upsert_response(session, day, "stress_hoog", True)
    entry = get_entry(session, day)
    assert entry.responses == {"alcohol": 2.0, "stress_hoog": True}

    # overwriting the same key updates in place
    upsert_response(session, day, "alcohol", 3.0)
    entry = get_entry(session, day)
    assert entry.responses["alcohol"] == 3.0


def test_upsert_entry_replaces_full_row(session: Session):
    day = date(2026, 8, 2)
    upsert_entry(session, day, {"alcohol": 1.0}, notes="feestje")
    upsert_entry(session, day, {"alcohol": 0.0, "ziek": True}, notes="beter")
    entry = get_entry(session, day)
    assert entry.responses == {"alcohol": 0.0, "ziek": True}
    assert entry.notes == "beter"


def test_entries_in_range(session: Session):
    for i in range(5):
        upsert_response(session, date(2026, 8, 1) + timedelta(days=i), "alcohol", float(i))
    rows = entries_in_range(session, date(2026, 8, 2), date(2026, 8, 4))
    assert [e.entry_date for e in rows] == [date(2026, 8, 2), date(2026, 8, 3), date(2026, 8, 4)]


def test_get_entry_missing_returns_none(session: Session):
    assert get_entry(session, date(2026, 1, 1)) is None


# ── insights.py: the gate ────────────────────────────────────────────

def _add_recovery(session: Session, day: date, score: float) -> None:
    session.add(ComputedScore(user_id=1, score_date=day, recovery_score=score))


def test_compute_insight_none_below_sample_gate(session: Session):
    # Only 3 exposed, 3 baseline days — below default min_samples=5
    base_day = date(2026, 7, 1)
    for i in range(3):
        d = base_day + timedelta(days=i)
        upsert_response(session, d, "alcohol", 2.0)  # exposed
        _add_recovery(session, d + timedelta(days=1), 40.0)
    for i in range(3, 6):
        d = base_day + timedelta(days=i)
        upsert_response(session, d, "alcohol", 0.0)  # baseline
        _add_recovery(session, d + timedelta(days=1), 70.0)
    session.commit()

    insight = compute_insight(session, "alcohol", "recovery_score", end=date(2026, 7, 10))
    assert insight is None  # under-powered — must not report


def test_compute_insight_reports_when_gate_cleared(session: Session):
    base_day = date(2026, 7, 1)
    # 5 exposed days (alcohol > 0) → lower recovery next day
    for i in range(5):
        d = base_day + timedelta(days=i)
        upsert_response(session, d, "alcohol", 2.0)
        _add_recovery(session, d + timedelta(days=1), 40.0)
    # 5 baseline days (no alcohol) → higher recovery next day
    for i in range(10, 15):
        d = base_day + timedelta(days=i)
        upsert_response(session, d, "alcohol", 0.0)
        _add_recovery(session, d + timedelta(days=1), 70.0)
    session.commit()

    insight = compute_insight(session, "alcohol", "recovery_score", end=date(2026, 7, 20))
    assert insight is not None
    assert insight.n_exposed == 5
    assert insight.n_baseline == 5
    assert insight.mean_exposed == 40.0
    assert insight.mean_baseline == 70.0
    assert insight.diff == -30.0
    assert insight.direction == "lager"
    assert insight.cohens_d == 0.0  # zero variance within each group → pooled SD 0 → d=0 by convention
    assert "alcohol" in insight.text().lower() or "Alcohol" in insight.text()


def test_compute_insight_unknown_factor_or_outcome_returns_none(session: Session):
    assert compute_insight(session, "not_a_factor", "recovery_score") is None
    assert compute_insight(session, "alcohol", "not_an_outcome") is None


def test_compute_insight_count_factor_exposed_is_value_gt_zero(session: Session):
    """Count factors (alcohol drinks): exposed = value > 0, not truthiness of the field."""
    base_day = date(2026, 6, 1)
    for i in range(5):
        d = base_day + timedelta(days=i)
        upsert_response(session, d, "alcohol", 3.0)
        _add_recovery(session, d + timedelta(days=1), 35.0)
    for i in range(10, 15):
        d = base_day + timedelta(days=i)
        upsert_response(session, d, "alcohol", 0.0)  # explicit zero = baseline, not "missing"
        _add_recovery(session, d + timedelta(days=1), 75.0)
    session.commit()
    insight = compute_insight(session, "alcohol", "recovery_score", end=date(2026, 6, 20))
    assert insight is not None
    assert insight.n_exposed == 5
    assert insight.n_baseline == 5


def test_compute_all_insights_sorted_by_effect_size(session: Session):
    base_day = date(2026, 5, 1)
    # strong effect: stress_hoog
    for i in range(5):
        d = base_day + timedelta(days=i)
        upsert_response(session, d, "stress_hoog", True)
        _add_recovery(session, d + timedelta(days=1), 30.0)
    for i in range(10, 15):
        d = base_day + timedelta(days=i)
        upsert_response(session, d, "stress_hoog", False)
        _add_recovery(session, d + timedelta(days=1), 80.0)
    session.commit()

    insights = compute_all_insights(session, end=date(2026, 5, 20))
    assert len(insights) >= 1
    assert insights[0].factor_key == "stress_hoog"
    # sorted descending by |cohens_d|
    ds = [abs(i.cohens_d) for i in insights]
    assert ds == sorted(ds, reverse=True)


def test_compute_insight_missing_outcome_days_are_skipped(session: Session):
    """A logged day with no recovery score the next day contributes nothing."""
    base_day = date(2026, 4, 1)
    for i in range(5):
        d = base_day + timedelta(days=i)
        upsert_response(session, d, "alcohol", 1.0)
        _add_recovery(session, d + timedelta(days=1), 50.0)
    # baseline days logged but their outcome day has no score at all
    for i in range(10, 15):
        upsert_response(session, base_day + timedelta(days=i), "alcohol", 0.0)
    session.commit()
    insight = compute_insight(session, "alcohol", "recovery_score", end=date(2026, 4, 20))
    assert insight is None  # baseline group has 0 usable outcomes < min_samples
