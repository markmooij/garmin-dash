"""Which journal factors to ask about today (Signal evening reminder).

The registry has more factors than fit in a readable Signal message, so
the reminder asks only `JOURNAL_PROMPT_FACTORS_PER_DAY` at a time. The
selection is *need-driven* rather than a blind cycle: the insight engine
needs >= JOURNAL_INSIGHT_MIN_SAMPLES days both WITH and WITHOUT a factor
before it reports anything, so the binding constraint for each factor is
`min(exposed_days, baseline_days)`. Factors furthest from clearing that
gate get asked first — that is the fastest route to an actual insight.

Ties (e.g. every factor at 0 days on a fresh install) rotate by date so
the same three are not asked forever, and factors already logged today
are skipped. The function is pure and deterministic for a given
(session, day): same inputs -> same questions, which keeps it testable
and makes a re-sent reminder consistent.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ..settings import get_settings
from .entries import entries_in_range, get_entry
from .insights import is_exposed
from .schema import FACTORS, Factor


if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.orm import Session


def _coverage(session: Session, day: date, user_id: int) -> dict[str, int]:
    """For each factor key: min(#days exposed, #days baseline) in the window.

    This mirrors the insight gate (`insights.compute_insight`), which needs
    both groups populated — so the smaller group is what actually blocks a
    factor from ever producing an insight.
    """
    settings = get_settings()
    start = day - timedelta(days=settings.JOURNAL_INSIGHT_WINDOW_DAYS)
    entries = entries_in_range(session, start, day, user_id=user_id)

    exposed: dict[str, int] = {f.key: 0 for f in FACTORS}
    baseline: dict[str, int] = {f.key: 0 for f in FACTORS}
    for entry in entries:
        for key, value in (entry.responses or {}).items():
            if key not in exposed:
                continue  # retired/unknown key: not asked, not counted
            # Reuse the engine's own exposure rule so coverage counts exactly
            # what the gate counts (incl. ignoring unparseable values).
            exposure = is_exposed(value)
            if exposure is None:
                continue
            if exposure:
                exposed[key] += 1
            else:
                baseline[key] += 1
    return {key: min(exposed[key], baseline[key]) for key in exposed}


def factors_for_day(
    session: Session,
    day: date,
    count: int | None = None,
    user_id: int = 1,
) -> list[Factor]:
    """The factors to ask about on `day`, most-needed first.

    Factors already logged for `day` are skipped (no point asking twice).
    When everything is already logged, returns an empty list and the
    caller shows a "done for today" message instead of a prompt.
    """
    settings = get_settings()
    count = settings.JOURNAL_PROMPT_FACTORS_PER_DAY if count is None else count
    if count <= 0:
        return []

    entry = get_entry(session, day, user_id=user_id)
    answered = set((entry.responses or {}).keys()) if entry else set()
    candidates = [f for f in FACTORS if f.key not in answered]
    if not candidates:
        return []

    coverage = _coverage(session, day, user_id)
    n = len(FACTORS)
    index_of = {f.key: i for i, f in enumerate(FACTORS)}
    offset = day.toordinal()

    def sort_key(f: Factor) -> tuple[int, int]:
        # 1. furthest from the insight gate first
        # 2. rotate among equals so the same three are not asked every day
        return (coverage.get(f.key, 0), (index_of[f.key] - offset) % n)

    return sorted(candidates, key=sort_key)[:count]


__all__ = ["factors_for_day"]
