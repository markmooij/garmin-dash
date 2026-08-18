"""Signal commands for the journal: /log, /journal, /insights (Phase 5).

Pure functions (session + text in, reply text out) — no messaging side
effects, matching `briefing.route_command`. Wired into
`briefing.route_command` so /log etc. answer through the same poll loop.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..journal.entries import get_entry, upsert_response
from ..journal.insights import compute_all_insights
from ..journal.schema import FACTORS, FACTORS_BY_KEY, parse_bool
from ..settings import get_settings


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_DUTCH_DAYS = [
    "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag",
]
_DUTCH_MONTHS = [
    "jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec",
]


def _dutch_date(day: date) -> str:
    return f"{_DUTCH_DAYS[day.weekday()]} {day.day} {_DUTCH_MONTHS[day.month - 1]}"


def _today(day: date | None) -> date:
    return day if day is not None else datetime.now(ZoneInfo(get_settings().TIMEZONE)).date()


def _factor_list_text() -> str:
    lines = [f"{f.key} — {f.label} ({f.prompt})" for f in FACTORS]
    return "\n".join(lines)


def log_prompt_text(day: date | None = None) -> str:
    """The evening reminder message (scheduler job, also /journal with no args)."""
    day = _today(day)
    return (
        f"📓 Dagboek {_dutch_date(day)}\n"
        "Log met: /log <factor> <j/n of aantal>\n\n"
        f"{_factor_list_text()}\n\n"
        "Voorbeeld: /log alcohol 2\n"
        "Voorbeeld: /log stress_hoog j"
    )


def route_log(session: Session, args: list[str], day: date | None = None) -> str:
    """/log <factor> <value> — record one factor for today."""
    day = _today(day)
    if len(args) < 2:
        return "Gebruik: /log <factor> <j/n of aantal>\n\n" + _factor_list_text()
    key, raw_value = args[0].lower(), args[1]
    factor = FACTORS_BY_KEY.get(key)
    if factor is None:
        return f"Onbekende factor: {key}\n\n" + _factor_list_text()

    if factor.kind == "bool":
        parsed = parse_bool(raw_value)
        if parsed is None:
            return f"Gebruik j/n voor {key}, bijv: /log {key} j"
        value: bool | float = parsed
    else:
        try:
            value = float(raw_value)
        except ValueError:
            return f"Gebruik een getal voor {key}, bijv: /log {key} 2"

    upsert_response(session, day, key, value)
    shown = "ja" if value is True else "nee" if value is False else f"{value:g}"
    return f"✅ Genoteerd — {factor.label} ({_dutch_date(day)}): {shown}"


def route_journal(session: Session, day: date | None = None) -> str:
    """/journal — show today's logged entry, or the prompt if nothing logged yet."""
    day = _today(day)
    entry = get_entry(session, day)
    if entry is None or not entry.responses:
        return log_prompt_text(day)
    lines = [f"📓 Dagboek {_dutch_date(day)}"]
    for key, value in entry.responses.items():
        factor = FACTORS_BY_KEY.get(key)
        label = factor.label if factor else key
        shown = "ja" if value is True else "nee" if value is False else f"{value:g}"
        lines.append(f"  {label}: {shown}")
    return "\n".join(lines)


def route_insights(session: Session, day: date | None = None) -> str:
    """/insights — gated correlation report (only factors clearing the sample gate)."""
    end = _today(day)
    insights = compute_all_insights(session, end=end)
    if not insights:
        settings = get_settings()
        return (
            "📈 Nog geen inzichten.\n"
            f"Elke factor heeft \u2265{settings.JOURNAL_INSIGHT_MIN_SAMPLES} gelogde dagen "
            "mét én zonder nodig om betrouwbaar te vergelijken. "
            "Blijf loggen met /log."
        )
    lines = ["📈 Inzichten (laatste " + str(get_settings().JOURNAL_INSIGHT_WINDOW_DAYS) + "d)"]
    for insight in insights[:5]:
        lines.append("• " + insight.text())
    return "\n".join(lines)


def build_weekly_digest(session: Session, end: date | None = None) -> str | None:
    """Weekly Signal digest text, or None if there is nothing gated to report."""
    end = _today(end)
    insights = compute_all_insights(session, end=end)
    if not insights:
        return None
    lines = [f"📈 Wekelijkse inzichten — t/m {_dutch_date(end)}"]
    for insight in insights[:5]:
        lines.append("• " + insight.text())
    return "\n".join(lines)


__all__ = [
    "build_weekly_digest",
    "log_prompt_text",
    "route_insights",
    "route_journal",
    "route_log",
]
