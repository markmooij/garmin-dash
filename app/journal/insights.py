"""Gated correlation insight engine (Phase 5).

Joins journal factors against outcome scores (recovery, sleep) shifted by
`JOURNAL_OUTCOME_OFFSET_DAYS` (a factor logged for day D describes what
happened during D; the behavioral effect shows up in the night D→D+1, so
the outcome is read from D + offset).

Hard rule (roadmap-locked): an insight is only reported when BOTH the
"exposed" and "baseline" groups have >= JOURNAL_INSIGHT_MIN_SAMPLES days
with a usable outcome value. Below threshold, the engine returns nothing
for that factor — never a partial or hedged claim. Output is always
direction + effect size (mean difference + Cohen's d) + window, explicitly
labeled *insight*; p-values are never computed or shown (roadmap decision).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..db.models import ComputedScore, SleepSession
from ..settings import get_settings
from .entries import entries_in_range
from .schema import FACTORS, FACTORS_BY_KEY, OUTCOME_LABELS, OUTCOMES


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

USER_ID = 1


@dataclass
class Insight:
    factor_key: str
    factor_label: str
    outcome_key: str
    outcome_label: str
    mean_exposed: float
    mean_baseline: float
    diff: float  # exposed - baseline
    cohens_d: float
    n_exposed: int
    n_baseline: int
    window_start: date
    window_end: date

    @property
    def direction(self) -> str:
        return "hoger" if self.diff >= 0 else "lager"

    @property
    def magnitude_label(self) -> str:
        d = abs(self.cohens_d)
        if d < 0.2:
            return "verwaarloosbaar"
        if d < 0.5:
            return "klein"
        if d < 0.8:
            return "gemiddeld"
        return "groot"

    def text(self) -> str:
        return (
            f"{self.factor_label} → {self.outcome_label}: {self.diff:+.1f} punten "
            f"gemiddeld ({self.direction}, effect {self.magnitude_label}) — "
            f"n={self.n_exposed} vs n={self.n_baseline}, "
            f"{self.window_start.isoformat()}–{self.window_end.isoformat()}"
        )


def _outcome_values(session: Session, user_id: int, start: date, end: date) -> dict[date, dict]:
    """{date: {"recovery_score": ..., "sleep_score": ...}} for [start, end]."""
    out: dict[date, dict] = {}
    scores = session.execute(
        select(ComputedScore.score_date, ComputedScore.recovery_score).where(
            ComputedScore.user_id == user_id,
            ComputedScore.score_date >= start,
            ComputedScore.score_date <= end,
        )
    ).all()
    for d, rec in scores:
        out.setdefault(d, {})["recovery_score"] = rec
    sleeps = session.execute(
        select(SleepSession.calendar_date, SleepSession.sleep_score).where(
            SleepSession.user_id == user_id,
            SleepSession.calendar_date >= start,
            SleepSession.calendar_date <= end,
        )
    ).all()
    for d, sc in sleeps:
        out.setdefault(d, {})["sleep_score"] = sc
    return out


def _is_exposed(value: object) -> bool | None:
    """Normalize a logged factor value to exposed(True)/baseline(False).

    Bool factors: value itself. Count factors (e.g. alcohol drinks):
    exposed = count > 0. Unparseable values are ignored (None).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    return None


def _cohens_d(a: list[float], b: list[float]) -> float:
    """Pooled-SD effect size. 0.0 when either group has < 2 points (no variance)."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    sa, sb = statistics.stdev(a), statistics.stdev(b)
    na, nb = len(a), len(b)
    pooled = (((na - 1) * sa**2) + ((nb - 1) * sb**2)) / (na + nb - 2)
    if pooled <= 0:
        return 0.0
    return (statistics.mean(a) - statistics.mean(b)) / (pooled**0.5)


def compute_insight(
    session: Session,
    factor_key: str,
    outcome_key: str,
    *,
    window_days: int | None = None,
    min_samples: int | None = None,
    offset_days: int | None = None,
    end: date | None = None,
    user_id: int = USER_ID,
) -> Insight | None:
    """One factor × outcome pair, gated. None if under-powered or unknown keys."""
    settings = get_settings()
    window_days = window_days or settings.JOURNAL_INSIGHT_WINDOW_DAYS
    min_samples = min_samples if min_samples is not None else settings.JOURNAL_INSIGHT_MIN_SAMPLES
    offset_days = offset_days if offset_days is not None else settings.JOURNAL_OUTCOME_OFFSET_DAYS
    factor = FACTORS_BY_KEY.get(factor_key)
    if factor is None or outcome_key not in OUTCOMES:
        return None

    end = end or date.today()
    start = end - timedelta(days=window_days - 1)
    entries = entries_in_range(session, start, end, user_id=user_id)
    outcome_start, outcome_end = start + timedelta(days=offset_days), end + timedelta(days=offset_days)
    outcomes = _outcome_values(session, user_id, outcome_start, outcome_end)

    exposed: list[float] = []
    baseline: list[float] = []
    for entry in entries:
        if factor_key not in entry.responses:
            continue
        is_exp = _is_exposed(entry.responses[factor_key])
        if is_exp is None:
            continue
        outcome_day = entry.entry_date + timedelta(days=offset_days)
        val = outcomes.get(outcome_day, {}).get(outcome_key)
        if val is None:
            continue
        (exposed if is_exp else baseline).append(float(val))

    if len(exposed) < min_samples or len(baseline) < min_samples:
        return None

    mean_exp, mean_base = statistics.mean(exposed), statistics.mean(baseline)
    return Insight(
        factor_key=factor_key,
        factor_label=factor.label,
        outcome_key=outcome_key,
        outcome_label=OUTCOME_LABELS[outcome_key],
        mean_exposed=mean_exp,
        mean_baseline=mean_base,
        diff=mean_exp - mean_base,
        cohens_d=_cohens_d(exposed, baseline),
        n_exposed=len(exposed),
        n_baseline=len(baseline),
        window_start=start,
        window_end=end,
    )


def compute_all_insights(
    session: Session, end: date | None = None, user_id: int = USER_ID
) -> list[Insight]:
    """Every factor × outcome pair that clears the sample gate, largest |d| first."""
    out: list[Insight] = []
    for factor in FACTORS:
        for outcome_key in OUTCOMES:
            insight = compute_insight(session, factor.key, outcome_key, end=end, user_id=user_id)
            if insight is not None:
                out.append(insight)
    out.sort(key=lambda i: abs(i.cohens_d), reverse=True)
    return out
