"""Grounded context assembly for the LLM coach.

Pulls exact numbers from the same read models the web UI and Signal
briefings use (`web.query`, `journal.insights`) — never re-derives or
free-forms anything. The LLM only ever sees this assembled context; it
is instructed (see `client.py`) to cite these numbers verbatim and never
invent figures. A test asserts every number the model outputs traces
back to a value in this context (see tests/test_coach.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from ..journal.entries import get_entry
from ..journal.insights import compute_all_insights
from ..journal.schema import FACTORS_BY_KEY
from ..settings import get_settings
from ..web.query import USER_ID, summary_for


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class CoachContext:
    """Everything the coach is allowed to talk about, as exact numbers."""

    today: date
    days: list[dict] = field(default_factory=list)  # trailing window, oldest first
    journal_today: dict = field(default_factory=dict)
    insights: list[dict] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Render as a compact, unambiguous text block for the LLM prompt."""
        lines: list[str] = [f"Vandaag: {self.today.isoformat()}", ""]
        lines.append(f"Laatste {len(self.days)} dagen (oud \u2192 nieuw):")
        for d in self.days:
            rec = f"{d['recovery_score']:.0f}" if d["recovery_score"] is not None else "\u2013"
            band = d["recovery_band"] or "\u2013"
            strain = f"{d['strain']:.1f}" if d["strain"] is not None else "\u2013"
            tsb = f"{d['tsb']:.1f}" if d["tsb"] is not None else "\u2013"
            sleep = f"{d['sleep_score']:.0f}" if d["sleep_score"] is not None else "\u2013"
            rhr = f"{d['rhr']:.0f}" if d["rhr"] is not None else "\u2013"
            lines.append(
                f"  {d['date']}: herstel={rec} ({band}), strain={strain}, TSB={tsb}, "
                f"slaap={sleep}, RHR={rhr}"
            )

        if self.journal_today:
            lines.append("")
            lines.append(f"Dagboek vandaag ({self.today.isoformat()}):")
            for key, value in self.journal_today.items():
                factor = FACTORS_BY_KEY.get(key)
                label = factor.label if factor else key
                shown = "ja" if value is True else "nee" if value is False else f"{value:g}"
                lines.append(f"  {label}: {shown}")

        if self.insights:
            lines.append("")
            lines.append("Gevalideerde inzichten (alleen deze mogen als correlatie genoemd worden):")
            for i in self.insights:
                lines.append(f"  {i['text']}")

        return "\n".join(lines)


def build_context(
    session: Session,
    day: date | None = None,
    window_days: int | None = None,
    user_id: int = USER_ID,
) -> CoachContext:
    """Assemble the trailing window + today's journal + gated insights.

    Baselines/insights are computed the same way the dashboard and Signal
    commands do (`summary_for`, `compute_all_insights`) — the coach never
    sees a different number than the user does.
    """
    settings = get_settings()
    day = day or date.today()
    window_days = window_days or settings.LLM_CONTEXT_WINDOW_DAYS

    days: list[dict] = []
    for i in range(window_days - 1, -1, -1):
        d = day - timedelta(days=i)
        data = summary_for(session, d)
        days.append(
            {
                "date": d.isoformat(),
                "recovery_score": data["recovery"]["score"],
                "recovery_band": data["recovery"]["band"],
                "strain": data["strain"],
                "tsb": data["tsb"],
                "atl": data["atl"],
                "ctl": data["ctl"],
                "sleep_score": data["sleep"]["score"],
                "rhr": data["wellness"]["rhr"],
            }
        )

    entry = get_entry(session, day, user_id=user_id)
    journal_today = dict(entry.responses) if entry else {}

    insights = [
        {
            "factor_label": i.factor_label,
            "outcome_label": i.outcome_label,
            "diff": round(i.diff, 1),
            "cohens_d": round(i.cohens_d, 2),
            "text": i.text(),
        }
        for i in compute_all_insights(session, end=day, user_id=user_id)
    ]

    return CoachContext(today=day, days=days, journal_today=journal_today, insights=insights)
