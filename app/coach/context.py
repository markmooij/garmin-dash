"""Grounded context assembly for the LLM coach.

Pulls exact numbers from the same read models the web UI and Signal
briefings use (`web.query`, `journal.insights`) — never re-derives or
free-forms anything. The LLM only ever sees this assembled context; it
is instructed (see `client.py`) to cite these numbers verbatim and never
invent figures. A test asserts every number the model outputs traces
back to a value in this context (see tests/test_coach.py).

The context deliberately carries MORE than the raw series: week-level
min/max/mean aggregates, sleep duration in hours and activities are all
computed HERE (trusted code) so a weekly question ("hoe was mijn
week?") can be answered without the model computing anything itself —
that is what keeps the "LLM never computes numbers" rule enforceable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from ..journal.entries import get_entry
from ..journal.insights import compute_all_insights
from ..journal.schema import get_factor
from ..settings import get_settings
from ..web.query import USER_ID, summary_for


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


_NL_WEEKDAYS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


def _day_label(d: date, today: date) -> str:
    if d == today:
        return "vandaag"
    if d == today - timedelta(days=1):
        return "gisteren"
    return _NL_WEEKDAYS[d.weekday()]


def _stats(values: list[float | None]) -> dict | None:
    """min/max/mean over present values; None when nothing present."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {"mean": sum(vals) / len(vals), "min": min(vals), "max": max(vals)}


@dataclass
class CoachContext:
    """Everything the coach is allowed to talk about, as exact numbers."""

    today: date
    days: list[dict] = field(default_factory=list)  # trailing window, oldest first
    aggregates: dict = field(default_factory=dict)  # week min/max/mean, app-computed
    activities: list[dict] = field(default_factory=list)  # name + minutes
    journal_today: dict = field(default_factory=dict)  # {factor_key: value}
    journal_labels: dict = field(default_factory=dict)  # {factor_key: label}
    insights: list[dict] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Render as a compact, unambiguous text block for the LLM prompt.

        Day labels are weekday names (vandaag/gisteren/maandag…) instead of
        ISO dates so the date digits don't pollute the grounding number
        space.
        """
        lines: list[str] = [f"Vandaag: {_NL_WEEKDAYS[self.today.weekday()]}", ""]
        lines.append(f"Laatste {len(self.days)} dagen (oud \u2192 nieuw):")
        for d in self.days:
            rec = f"{d['recovery_score']:.0f}" if d["recovery_score"] is not None else "\u2013"
            band = d["recovery_band"] or "\u2013"
            strain = f"{d['strain']:.1f}" if d["strain"] is not None else "\u2013"
            tsb = f"{d['tsb']:.1f}" if d["tsb"] is not None else "\u2013"
            sleep = f"{d['sleep_score']:.0f}" if d["sleep_score"] is not None else "\u2013"
            hours = f" ({d['sleep_hours']:.1f}u)" if d.get("sleep_hours") else ""
            rhr = f"{d['rhr']:.0f}" if d["rhr"] is not None else "\u2013"
            lines.append(
                f"  {d['label']}: herstel={rec} ({band}), strain={strain}, TSB={tsb}, "
                f"slaap={sleep}{hours}, RHR={rhr}"
            )

        # Week-level stats are computed HERE (trusted code), never by the
        # model — so a weekly summary can cite min/max/mean without violating
        # the "LLM never computes numbers" rule (and without tripping grounding).
        a = self.aggregates
        if a and any(a.get(k) is not None for k in ("recovery", "strain", "sleep", "rhr", "tsb", "sleep_duration_h")):

            def _fmt_range(key: str, decimals: int) -> str | None:
                s = a.get(key)
                if not s:
                    return None
                return f"{s['min']:.{decimals}f}\u2013{s['max']:.{decimals}f} (gem {s['mean']:.{decimals}f})"

            lines.append("")
            lines.append("Weekoverzicht (min-max en gemiddelden berekend door de app):")
            parts = [p for p in (
                ("herstel", _fmt_range("recovery", 0)),
                ("strain", _fmt_range("strain", 1)),
                ("slaap", _fmt_range("sleep", 0)),
            ) if p[1] is not None]
            if parts:
                lines.append("  " + " \u00b7 ".join(f"{label} {r}" for label, r in parts))
            extra: list[str] = []
            sd = a.get("sleep_duration_h")
            if sd:
                extra.append(f"slaapduur {sd:.1f}u")
            rhr = a.get("rhr")
            if rhr:
                extra.append(f"RHR {rhr['mean']:.0f}")
            tsb = a.get("tsb")
            if tsb:
                extra.append(f"TSB {tsb['mean']:.1f}")
            extra.append(f"trainingsdagen {a.get('training_days', 0)}")
            extra.append(f"rustdagen {a.get('rest_days', 0)}")
            lines.append("  " + " \u00b7 ".join(extra))

        if self.activities:
            lines.append("")
            lines.append("Activiteiten (laatste 7 dagen):")
            for act in self.activities:
                name = act.get("name") or act.get("type") or "activiteit"
                minutes = act.get("minutes")
                lines.append(f"  \u2022 {name}: {minutes} min" if minutes else f"  \u2022 {name}")

        if self.journal_today:
            lines.append("")
            lines.append(f"Dagboek vandaag ({_NL_WEEKDAYS[self.today.weekday()]}):")
            for key, value in self.journal_today.items():
                label = self.journal_labels.get(key, key)
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
    activities: list[dict] = []
    for i in range(window_days - 1, -1, -1):
        d = day - timedelta(days=i)
        data = summary_for(session, d)
        total_s = data["sleep"].get("total_s")
        days.append(
            {
                "date": d.isoformat(),
                "label": _day_label(d, day),
                "recovery_score": data["recovery"]["score"],
                "recovery_band": data["recovery"]["band"],
                "strain": data["strain"],
                "tsb": data["tsb"],
                "atl": data["atl"],
                "ctl": data["ctl"],
                "sleep_score": data["sleep"]["score"],
                "sleep_hours": total_s / 3600 if total_s else None,
                "rhr": data["wellness"]["rhr"],
            }
        )
        for act in data["activities"]:
            duration_s = act.get("duration_s")
            activities.append(
                {
                    "name": act.get("name"),
                    "type": act.get("type"),
                    "minutes": round(duration_s / 60) if duration_s else None,
                }
            )

    entry = get_entry(session, day, user_id=user_id)
    journal_today = dict(entry.responses) if entry else {}
    journal_labels: dict[str, str] = {}
    for key in journal_today:
        factor = get_factor(session, key, user_id=user_id)
        journal_labels[key] = factor.label if factor else key

    aggregates: dict = {}
    if days:
        sleep_h = _stats([d["sleep_hours"] for d in days])
        aggregates = {
            "recovery": _stats([d["recovery_score"] for d in days]),
            "strain": _stats([d["strain"] for d in days]),
            "sleep": _stats([d["sleep_score"] for d in days]),
            "sleep_duration_h": sleep_h["mean"] if sleep_h else None,
            "rhr": _stats([d["rhr"] for d in days]),
            "tsb": _stats([d["tsb"] for d in days]),
            "training_days": sum(1 for d in days if (d["strain"] or 0) > 0),
            "rest_days": sum(1 for d in days if d["strain"] is not None and d["strain"] <= 0),
        }

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

    return CoachContext(
        today=day,
        days=days,
        aggregates=aggregates,
        activities=activities,
        journal_today=journal_today,
        journal_labels=journal_labels,
        insights=insights,
    )
