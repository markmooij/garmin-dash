"""LLM interpretation of gated insights (Phase 5.5).

Each insight is a computed correlation (factor → outcome) with exact stats.
The LLM never computes anything — it is handed the exact numbers and asked
to word what they mean in plain Dutch. The same grounding check that guards
the coach drops any reply that cites a number not in the context, so a
hallucinated figure never reaches the user.

Interpretations are cached in `insight_interpretations`, keyed by a hash of
the insight's exact stats. The stats shift daily as new data lands (the
window slides), so the hash changes and the interpretation is regenerated;
while the numbers are unchanged the cached text is reused verbatim — the
page never hammers the LLM.

Failed attempts are cached too. An insight the model cannot describe
groundedly used to be retried on every single page load, costing a
multi-second round-trip each time for a reply that was dropped again; the
negative cache turns that into a single lookup. Insights whose effect is
negligible (|d| < INSIGHTS_LLM_MIN_EFFECT) are never sent to the LLM at
all — there is nothing to explain, and asking invites exactly the kind of
ungrounded number the grounding check throws away.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..db.models import InsightInterpretation
from ..settings import get_settings


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..journal.insights import Insight

logger = logging.getLogger("garmin_dash.coach.interpretation")


def _is_negligible(insight: Insight, min_effect: float) -> bool:
    """True when the insight is too small to be worth an LLM round-trip.

    Deliberately conservative: `_cohens_d` returns a sentinel 0.0 both for a
    genuine zero effect and for "cannot compute" (fewer than 2 points in a
    group, or zero pooled variance). Keying the skip on d alone would
    therefore suppress the explanation for a *huge* but zero-variance effect
    (e.g. every exposed day 30, every baseline day 80). So a small d only
    counts as negligible when the mean difference is small as well — if the
    means are far apart there is something real to explain, whatever d says.
    """
    if abs(insight.cohens_d) >= min_effect:
        return False
    return abs(insight.diff) < _NEGLIGIBLE_DIFF_POINTS


# Outcome scores are 0-100; a gap under this many points is noise-level and
# is what the card already labels "verwaarloosbaar".
_NEGLIGIBLE_DIFF_POINTS = 2.0


def _data_hash(insight: Insight) -> str:
    """Stable hash of the insight's exact numbers (changes when stats move)."""
    payload = (
        f"{insight.mean_exposed:.4f}|{insight.mean_baseline:.4f}|{insight.diff:.4f}|"
        f"{insight.cohens_d:.4f}|{insight.n_exposed}|{insight.n_baseline}|"
        f"{insight.window_start.isoformat()}|{insight.window_end.isoformat()}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _context_text(insight: Insight) -> str:
    """The exact numbers the LLM may cite (grounding context)."""
    return (
        f"Inzicht: {insight.factor_label} → {insight.outcome_label}\n"
        f"- Gemiddelde {insight.outcome_label} met {insight.factor_label.lower()}: "
        f"{insight.mean_exposed:.1f} (n={insight.n_exposed})\n"
        f"- Gemiddelde {insight.outcome_label} zonder {insight.factor_label.lower()}: "
        f"{insight.mean_baseline:.1f} (n={insight.n_baseline})\n"
        f"- Verschil: {insight.diff:+.1f} punten ({insight.direction})\n"
        f"- Cohen's d: {insight.cohens_d:.2f} ({insight.magnitude_label})\n"
        f"- Venster: {insight.window_start.isoformat()} t/m {insight.window_end.isoformat()}"
    )


def _interpret_one(client, insight: Insight) -> tuple[str | None, str | None]:
    """One grounded LLM interpretation.

    Returns (text, failure): (text, None) on success, or (None, reason)
    where reason is "error" or "ungrounded". The reason is surfaced so the
    caller can negative-cache it instead of retrying every page load.
    """
    from .client import _grounded_reply

    context = _context_text(insight)
    prompt = (
        f"{context}\n\n"
        "Leg in maximaal 3 zinnen in het Nederlands uit wat dit verband betekent "
        "voor de gebruiker. Gebruik alleen bovenstaande cijfers, verzin niets en "
        "noem geen getallen die er niet staan."
    )
    return _grounded_reply(client, context, prompt)


def interpret_insights(
    session: Session,
    insights: list[Insight],
    *,
    max_new: int | None = None,
    user_id: int = 1,
) -> dict[int, str]:
    """Resolve interpretations for `insights` (index → text).

    Reuses cached text for unchanged stats, generates at most `max_new`
    (default INSIGHTS_LLM_MAX_PER_LOAD) fresh ones per call and stores them,
    and leaves the rest without an entry (the UI simply omits the block).
    Returns {} when the LLM is disabled.

    Two guards keep this off the slow path: insights with a negligible
    effect are skipped outright, and an attempt that failed for these exact
    numbers is not repeated (see the module docstring).
    """
    settings = get_settings()
    max_new = settings.INSIGHTS_LLM_MAX_PER_LOAD if max_new is None else max_new
    min_effect = settings.INSIGHTS_LLM_MIN_EFFECT
    from .client import get_client

    client = get_client()
    if client is None or not insights:
        return {}

    out: dict[int, str] = {}
    generated = 0
    for idx, insight in enumerate(insights):
        h = _data_hash(insight)
        row = session.execute(
            select(
                InsightInterpretation.interpretation,
                InsightInterpretation.failure,
            ).where(
                InsightInterpretation.user_id == user_id,
                InsightInterpretation.factor_key == insight.factor_key,
                InsightInterpretation.outcome_key == insight.outcome_key,
                InsightInterpretation.data_hash == h,
            )
        ).first()
        if row is not None:
            cached, failure = row
            if cached:
                out[idx] = cached
            # A recorded failure means "already tried these exact numbers and
            # the reply was unusable" — don't burn another round-trip on it.
            continue
        if _is_negligible(insight, min_effect):
            continue  # negligible effect — nothing worth an LLM call
        if generated >= max_new:
            continue  # leave a placeholder; next load fills more
        text, failure = _interpret_one(client, insight)
        session.add(
            InsightInterpretation(
                user_id=user_id,
                factor_key=insight.factor_key,
                outcome_key=insight.outcome_key,
                data_hash=h,
                interpretation=text,
                failure=failure,
            )
        )
        generated += 1
        if text:
            out[idx] = text
        else:
            logger.info(
                "Interpretation unavailable (%s) for %s→%s — cached to avoid retry",
                failure,
                insight.factor_key,
                insight.outcome_key,
            )
    if generated:
        session.commit()  # deliberate side effect: persist attempts (incl. failures)
    return out


__all__ = ["interpret_insights"]
