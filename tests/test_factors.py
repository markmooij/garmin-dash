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
    """An ungrounded reply must never reach the user.

    The failure *is* recorded (so it isn't retried every load), but the bad
    text itself is never stored and never returned.
    """
    from app.coach import interpretation
    from app.db.models import InsightInterpretation

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
    assert out == {}  # dropped — never surfaced
    rows = session.query(InsightInterpretation).all()
    assert rows  # the attempt is remembered
    assert all(r.interpretation is None for r in rows)  # but no bad text stored
    assert all(r.failure == "ungrounded" for r in rows)


# ── slow-page fixes: negative cache + negligible-effect skip ──────────

def test_failed_interpretation_is_not_retried_on_next_load(
    monkeypatch, session: Session
):
    """The fix for the slow /insights page: one attempt, not one per load."""
    from app.coach import interpretation

    _seed_insight_data(session, date(2026, 5, 1))
    insights = compute_all_insights(session, end=date(2026, 6, 20))
    calls = {"n": 0}

    class _FakeClient:  # noqa: D401
        pass

    def fake_grounded(client, context, prompt):  # noqa: ARG001
        calls["n"] += 1
        return None, "ungrounded"

    monkeypatch.setattr("app.coach.client.get_client", lambda: _FakeClient())
    monkeypatch.setattr("app.coach.client._grounded_reply", fake_grounded)

    interpretation.interpret_insights(session, insights, max_new=5)
    assert calls["n"] == len(insights)  # one attempt each

    # every later page load must cost zero LLM round-trips
    interpretation.interpret_insights(session, insights, max_new=5)
    interpretation.interpret_insights(session, insights, max_new=5)
    assert calls["n"] == len(insights)


def test_failed_interpretation_retried_when_stats_change(monkeypatch, session: Session):
    """The negative cache is keyed by data_hash, so new numbers get a retry."""
    from app.coach import interpretation

    _seed_insight_data(session, date(2026, 5, 1))
    insights = compute_all_insights(session, end=date(2026, 6, 20))
    calls = {"n": 0}

    class _FakeClient:  # noqa: D401
        pass

    def fake_grounded(client, context, prompt):  # noqa: ARG001
        calls["n"] += 1
        return None, "ungrounded"

    monkeypatch.setattr("app.coach.client.get_client", lambda: _FakeClient())
    monkeypatch.setattr("app.coach.client._grounded_reply", fake_grounded)

    interpretation.interpret_insights(session, insights, max_new=5)
    before = calls["n"]

    # alcohol's numbers move → new hash → fresh attempt for that insight
    upsert_response(session, date(2026, 6, 5), "alcohol", 2.0)
    session.add(ComputedScore(user_id=1, score_date=date(2026, 6, 6), recovery_score=25.0))
    session.commit()
    insights2 = compute_all_insights(session, end=date(2026, 6, 20))
    interpretation.interpret_insights(session, insights2, max_new=5)
    assert calls["n"] == before + 1


def test_recovered_interpretation_replaces_failure(monkeypatch, session: Session):
    """Once the numbers move and the model succeeds, the text is served."""
    from app.coach import interpretation

    _seed_insight_data(session, date(2026, 5, 1))
    insights = compute_all_insights(session, end=date(2026, 6, 20))
    state = {"fail": True}

    class _FakeClient:  # noqa: D401
        pass

    def fake_grounded(client, context, prompt):  # noqa: ARG001
        if state["fail"]:
            return None, "ungrounded"
        return "Nette uitleg.", None

    monkeypatch.setattr("app.coach.client.get_client", lambda: _FakeClient())
    monkeypatch.setattr("app.coach.client._grounded_reply", fake_grounded)

    assert interpretation.interpret_insights(session, insights, max_new=5) == {}

    state["fail"] = False
    upsert_response(session, date(2026, 6, 5), "alcohol", 2.0)
    session.add(ComputedScore(user_id=1, score_date=date(2026, 6, 6), recovery_score=25.0))
    session.commit()
    insights2 = compute_all_insights(session, end=date(2026, 6, 20))
    out = interpretation.interpret_insights(session, insights2, max_new=5)
    assert "Nette uitleg." in out.values()


def test_negligible_effect_skips_llm_entirely(monkeypatch, session: Session):
    """A tiny effect costs no LLM round-trip and stores nothing."""
    from app.coach import interpretation
    from app.db.models import InsightInterpretation
    from app.journal.insights import Insight

    calls = {"n": 0}

    class _FakeClient:  # noqa: D401
        pass

    def fake_grounded(client, context, prompt):  # noqa: ARG001
        calls["n"] += 1
        return "tekst", None

    monkeypatch.setattr("app.coach.client.get_client", lambda: _FakeClient())
    monkeypatch.setattr("app.coach.client._grounded_reply", fake_grounded)

    tiny = Insight(
        factor_key="laat_gewerkt", factor_label="Laat gewerkt",
        outcome_key="recovery_score", outcome_label="herstel",
        mean_exposed=50.4, mean_baseline=51.0, diff=-0.6, cohens_d=-0.07,
        n_exposed=6, n_baseline=9,
        window_start=date(2026, 5, 1), window_end=date(2026, 6, 20),
        last_sample_date=date(2026, 6, 20),
    )
    out = interpretation.interpret_insights(session, [tiny], max_new=5)
    assert out == {}
    assert calls["n"] == 0  # never asked the model
    assert session.query(InsightInterpretation).all() == []  # nothing cached


def test_large_effect_with_zero_variance_is_still_interpreted(
    monkeypatch, session: Session
):
    """cohens_d is 0.0 both for "no effect" and "cannot compute".

    A 30-vs-80 gap with no within-group variance yields d=0.0, but it is a
    huge real effect — it must not be mistaken for negligible and skipped.
    """
    from app.coach import interpretation
    from app.journal.insights import Insight

    calls = {"n": 0}

    class _FakeClient:  # noqa: D401
        pass

    def fake_grounded(client, context, prompt):  # noqa: ARG001
        calls["n"] += 1
        return "Groot effect.", None

    monkeypatch.setattr("app.coach.client.get_client", lambda: _FakeClient())
    monkeypatch.setattr("app.coach.client._grounded_reply", fake_grounded)

    big = Insight(
        factor_key="alcohol", factor_label="Alcohol",
        outcome_key="recovery_score", outcome_label="herstel",
        mean_exposed=30.0, mean_baseline=80.0, diff=-50.0, cohens_d=0.0,
        n_exposed=5, n_baseline=5,
        window_start=date(2026, 5, 1), window_end=date(2026, 6, 20),
        last_sample_date=date(2026, 6, 20),
    )
    out = interpretation.interpret_insights(session, [big], max_new=5)
    assert calls["n"] == 1  # asked despite d == 0.0
    assert out[0] == "Groot effect."
