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


def _interpret_one(client, insight: Insight) -> str | None:
    """One grounded LLM interpretation. None on error or ungrounded reply."""
    from .client import _grounded_reply

    context = _context_text(insight)
    prompt = (
        f"{context}\n\n"
        "Leg in maximaal 3 zinnen in het Nederlands uit wat dit verband betekent "
        "voor de gebruiker. Gebruik alleen bovenstaande cijfers, verzin niets en "
        "noem geen getallen die er niet staan."
    )
    reply, _failure = _grounded_reply(client, context, prompt)
    return reply


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
    and leaves the rest without an entry (the UI shows a subtle placeholder
    that fills in on a later load). Returns {} when the LLM is disabled.
    """
    settings = get_settings()
    max_new = settings.INSIGHTS_LLM_MAX_PER_LOAD if max_new is None else max_new
    from .client import get_client

    client = get_client()
    if client is None or not insights:
        return {}

    out: dict[int, str] = {}
    generated = 0
    for idx, insight in enumerate(insights):
        h = _data_hash(insight)
        cached = session.execute(
            select(InsightInterpretation.interpretation).where(
                InsightInterpretation.user_id == user_id,
                InsightInterpretation.factor_key == insight.factor_key,
                InsightInterpretation.outcome_key == insight.outcome_key,
                InsightInterpretation.data_hash == h,
            )
        ).scalar_one_or_none()
        if cached:
            out[idx] = cached
            continue
        if generated >= max_new:
            continue  # leave a placeholder; next load fills more
        text = _interpret_one(client, insight)
        if text:
            session.add(
                InsightInterpretation(
                    user_id=user_id,
                    factor_key=insight.factor_key,
                    outcome_key=insight.outcome_key,
                    data_hash=h,
                    interpretation=text,
                )
            )
            out[idx] = text
            generated += 1
    if generated:
        session.commit()  # deliberate side effect: persist the new interpretations
    return out


__all__ = ["interpret_insights"]
