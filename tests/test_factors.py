"""Phase 5.5: DB-backed factor registry, insight sorting/cap, LLM interpretation."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from app.db.models import ComputedScore, SleepSession
from app.journal.entries import upsert_response
from app.journal.insights import compute_all_insights
from app.journal.schema import (
    DEFAULT_FACTORS,
    create_factor,
    delete_factor,
    get_factor,
    get_factors,
    seed_factors,
    update_factor,
)
from app.web import query


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── factor registry (schema.py) ───────────────────────────────────────

def test_seed_factors_idempotent(session: Session):
    assert seed_factors(session) == 0  # already seeded by fixture
    assert len(get_factors(session)) == len(DEFAULT_FACTORS)


def test_get_factors_returns_seeded_defaults(session: Session):
    factors = get_factors(session)
    assert [f.key for f in factors] == [f.key for f in DEFAULT_FACTORS]
    assert factors[0].label == "Alcohol"
    assert factors[0].kind == "count"


def test_create_factor_appends_and_validates(session: Session):
    f = create_factor(session, "meditatie", "Meditatie", "bool", "10+ min gemediteerd")
    assert f.key == "meditatie"
    assert get_factor(session, "meditatie").label == "Meditatie"
    # appended last
    assert get_factors(session)[-1].key == "meditatie"

    with pytest.raises(ValueError):
        create_factor(session, "Ongeldige Sleutel!", "x", "bool", "y")
    with pytest.raises(ValueError):
        create_factor(session, "goed", "", "bool", "y")  # empty label
    with pytest.raises(ValueError):
        create_factor(session, "goed", "Goed", "weird", "y")  # bad kind
    with pytest.raises(ValueError):
        create_factor(session, "goed", "Goed", "bool", "")  # empty prompt


def test_create_factor_reactivates_soft_deleted(session: Session):
    delete_factor(session, "sauna")
    assert get_factor(session, "sauna").active is False
    assert "sauna" not in [f.key for f in get_factors(session)]
    f = create_factor(session, "sauna", "Sauna (nieuw)", "bool", "sauna bezocht")
    assert f.key == "sauna"
    assert get_factor(session, "sauna").active is True
    assert get_factor(session, "sauna").label == "Sauna (nieuw)"


def test_update_factor_edits_fields(session: Session):
    update_factor(session, "alcohol", label="Drankjes", kind="count", prompt="aantal glazen")
    f = get_factor(session, "alcohol")
    assert f.label == "Drankjes"
    assert f.prompt == "aantal glazen"


def test_delete_factor_soft_deletes(session: Session):
    assert delete_factor(session, "alcohol") is True
    assert get_factor(session, "alcohol").active is False
    assert "alcohol" not in [f.key for f in get_factors(session)]
    # data preserved — re-adding reactivates (covered above)


def test_delete_factor_unknown_returns_false(session: Session):
    assert delete_factor(session, "nope") is False


# ── insight sorting + cap (query.insights_for) ────────────────────────

def _seed_insight_data(session: Session, base: date) -> None:
    """Two factors with different effect sizes + sample dates."""
    # alcohol → recovery: strong negative (older window)
    for i in range(5):
        d = base + timedelta(days=i)
        upsert_response(session, d, "alcohol", 3.0)
        session.add(ComputedScore(user_id=1, score_date=d + timedelta(days=1), recovery_score=30.0))
    for i in range(10, 15):
        d = base + timedelta(days=i)
        upsert_response(session, d, "alcohol", 0.0)
        session.add(ComputedScore(user_id=1, score_date=d + timedelta(days=1), recovery_score=80.0))
    # stress_hoog → recovery: weaker positive (more recent window)
    for i in range(20, 25):
        d = base + timedelta(days=i)
        upsert_response(session, d, "stress_hoog", True)
        session.add(ComputedScore(user_id=1, score_date=d + timedelta(days=1), recovery_score=60.0))
    for i in range(30, 35):
        d = base + timedelta(days=i)
        upsert_response(session, d, "stress_hoog", False)
        session.add(ComputedScore(user_id=1, score_date=d + timedelta(days=1), recovery_score=50.0))
    session.commit()


def test_insights_for_default_sort_is_effect_desc(session: Session):
    _seed_insight_data(session, date(2026, 5, 1))
    d = query.insights_for(session, end=date(2026, 6, 20))
    assert len(d["insights"]) == 2
    # alcohol has the larger |diff| → first under effect sort
    assert d["insights"][0]["factor_key"] == "alcohol"
    assert d["insights"][1]["factor_key"] == "stress_hoog"


def test_insights_for_sort_by_date(session: Session):
    _seed_insight_data(session, date(2026, 5, 1))
    d = query.insights_for(session, end=date(2026, 6, 20), sort="date", direction="desc")
    # stress_hoog has the more recent samples → first
    assert d["insights"][0]["factor_key"] == "stress_hoog"
    assert d["insights"][0]["last_sample_date"] > d["insights"][1]["last_sample_date"]


def test_insights_for_sort_by_alphabet(session: Session):
    _seed_insight_data(session, date(2026, 5, 1))
    d = query.insights_for(session, end=date(2026, 6, 20), sort="alphabet", direction="asc")
    assert d["insights"][0]["factor_label"] == "Alcohol"  # A < H
    d2 = query.insights_for(session, end=date(2026, 6, 20), sort="alphabet", direction="desc")
    assert d2["insights"][0]["factor_label"] == "Hoge stress"


def test_insights_for_caps_at_max_display(session: Session):
    """More than INSIGHTS_MAX_DISPLAY gated insights → only the top N shown."""
    base = date(2026, 1, 25)
    end = date(2026, 4, 20)
    # 5 factors × 2 outcomes = 10 gated insights (> 8). Each factor gets a
    # disjoint 10-day range so computed_scores (unique on score_date) never
    # collides; both outcomes are set so each factor yields two insights.
    for idx, factor in enumerate(get_factors(session)[:5]):
        for i in range(5):
            d = base + timedelta(days=idx * 10 + i)
            upsert_response(session, d, factor.key, 3.0 if factor.kind == "count" else True)
            score_day = d + timedelta(days=1)
            session.add(
                ComputedScore(
                    user_id=1,
                    score_date=score_day,
                    recovery_score=float(20 + idx),
                )
            )
            session.add(
                SleepSession(
                    user_id=1,
                    calendar_date=score_day,
                    sleep_start_gmt=datetime.combine(score_day, datetime.min.time(), tzinfo=UTC),
                    sleep_end_gmt=datetime.combine(score_day, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=1),
                    sleep_score=int(30 + idx),
                )
            )
        for i in range(5, 10):
            d = base + timedelta(days=idx * 10 + i)
            upsert_response(session, d, factor.key, 0.0 if factor.kind == "count" else False)
            score_day = d + timedelta(days=1)
            session.add(
                ComputedScore(
                    user_id=1,
                    score_date=score_day,
                    recovery_score=float(70 + idx),
                )
            )
            session.add(
                SleepSession(
                    user_id=1,
                    calendar_date=score_day,
                    sleep_start_gmt=datetime.combine(score_day, datetime.min.time(), tzinfo=UTC),
                    sleep_end_gmt=datetime.combine(score_day, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=1),
                    sleep_score=int(80 + idx),
                )
            )
    session.commit()
    d = query.insights_for(session, end=end)
    assert d["total"] > 8
    assert len(d["insights"]) == 8  # INSIGHTS_MAX_DISPLAY
    assert d["limit"] == 8


def test_insights_for_unknown_sort_falls_back_to_effect(session: Session):
    _seed_insight_data(session, date(2026, 5, 1))
    d = query.insights_for(session, end=date(2026, 6, 20), sort="bogus")
    assert d["sort"] == "effect"


# ── LLM interpretation (coach/interpretation.py) ──────────────────────

def test_interpret_insights_returns_empty_when_llm_disabled(session: Session):
    from app.coach.interpretation import interpret_insights

    _seed_insight_data(session, date(2026, 5, 1))
    insights = compute_all_insights(session, end=date(2026, 6, 20))
    assert insights
    # LLM_ENABLED defaults False in tests → get_client() is None
    assert interpret_insights(session, insights) == {}


def test_interpret_insights_caches_and_bounds(monkeypatch, session: Session):
    from app.coach import interpretation

    _seed_insight_data(session, date(2026, 5, 1))
    insights = compute_all_insights(session, end=date(2026, 6, 20))
    assert len(insights) == 2

    calls = {"n": 0}

    class _FakeClient:  # noqa: D401
        pass

    def fake_grounded(client, context, prompt):  # noqa: ARG001
        calls["n"] += 1
        return f"Interpretatie {calls['n']} voor {context.splitlines()[0]}", None

    monkeypatch.setattr("app.coach.client.get_client", lambda: _FakeClient())
    monkeypatch.setattr("app.coach.client._grounded_reply", fake_grounded)

    # max_new=1 → only one generated per call
    out1 = interpretation.interpret_insights(session, insights, max_new=1)
    assert len(out1) == 1
    assert calls["n"] == 1

    # second call: cached entry reused, one new generated (max_new=1)
    out2 = interpretation.interpret_insights(session, insights, max_new=1)
    assert len(out2) == 2  # 1 cached + 1 new
    assert calls["n"] == 2
    assert out2[0] == out1[0]  # cached text identical

    # third call: everything cached, nothing generated
    out3 = interpretation.interpret_insights(session, insights, max_new=1)
    assert len(out3) == 2
    assert calls["n"] == 2


def test_interpret_insights_regenerates_when_stats_change(monkeypatch, session: Session):
    from app.coach import interpretation

    _seed_insight_data(session, date(2026, 5, 1))
    insights = compute_all_insights(session, end=date(2026, 6, 20))
    assert len(insights) == 2

    texts: list[str] = []

    class _FakeClient:  # noqa: D401
        pass

    def fake_grounded(client, context, prompt):  # noqa: ARG001
        texts.append(context.splitlines()[0])
        return f"tekst-{len(texts)}", None

    monkeypatch.setattr("app.coach.client.get_client", lambda: _FakeClient())
    monkeypatch.setattr("app.coach.client._grounded_reply", fake_grounded)

    interpretation.interpret_insights(session, insights, max_new=5)
    assert len(texts) == 2

    # same stats → cached, no regeneration
    interpretation.interpret_insights(session, insights, max_new=5)
    assert len(texts) == 2

    # stats move (new outcome day for alcohol) → alcohol's hash changes →
    # regenerated; stress_hoog's stats are unchanged → stays cached.
    upsert_response(session, date(2026, 6, 5), "alcohol", 2.0)
    session.add(ComputedScore(user_id=1, score_date=date(2026, 6, 6), recovery_score=25.0))
    session.commit()
    insights2 = compute_all_insights(session, end=date(2026, 6, 20))
    interpretation.interpret_insights(session, insights2, max_new=5)
    assert len(texts) == 3  # alcohol regenerated, stress_hoog cached
    assert texts[-1] == "Inzicht: Alcohol → herstel"


def test_interpret_insights_ungrounded_reply_is_dropped(monkeypatch, session: Session):
    """A reply that fails grounding (None reply) must not be persisted."""
    from app.coach import interpretation

    _seed_insight_data(session, date(2026, 5, 1))
    insights = compute_all_insights(session, end=date(2026, 6, 20))

    class _FakeClient:  # noqa: D401
        pass

    def fake_grounded(client, context, prompt):  # noqa: ARG001
        # mimics the real _grounded_reply: ungrounded → (None, "ungrounded")
        return None, "ungrounded"

    monkeypatch.setattr("app.coach.client.get_client", lambda: _FakeClient())
    monkeypatch.setattr("app.coach.client._grounded_reply", fake_grounded)

    out = interpretation.interpret_insights(session, insights, max_new=5)
    assert out == {}  # dropped, never stored
