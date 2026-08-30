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
from ..journal.rotation import factors_for_day
from ..journal.schema import FACTORS, Factor, get_factor, get_factors, parse_bool
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


def _factor_list_text(factors: list[Factor]) -> str:
    """Numbered list of the factors to answer, key + short prompt.

    The key is what the user types after /log, so it stays visible; the
    verbose label is reserved for /journal replies and the web form.
    """
    lines = [f"{i}. {f.key} — {f.prompt}" for i, f in enumerate(factors, 1)]
    return "\n".join(lines)


def _dashboard_link(path: str = "/journal") -> str:
    """'🔗 Meer invullen: <url>' line, or '' when DASHBOARD_URL is unset.

    Kept out of the message entirely when unconfigured — a wrong/placeholder
    URL in a daily message is worse than no link. A startup warning in
    `web/__init__.py` reminds operators to set DASHBOARD_URL when Signal is
    enabled.
    """
    base = (get_settings().DASHBOARD_URL or "").rstrip("/")
    if not base:
        return ""
    return f"\n\n🔗 Meer invullen op het dashboard: {base}{path}"


def log_prompt_text(
    day: date | None = None, factors: list[Factor] | None = None
) -> str:
    """The evening reminder message (scheduler job, also /journal with no args).

    Deliberately minimal — the user asked not to be bothered with a wall of
    text: at most `JOURNAL_PROMPT_FACTORS_PER_DAY` (3) questions, one
    instruction line, and a link to the dashboard for everything else.

    `factors` is the rotated subset chosen by `rotation.factors_for_day`;
    when omitted the default seed registry is listed (used by tests). An
    empty list means everything is already logged today.
    """
    day = _today(day)
    header = f"📓 Dagboek {_dutch_date(day)}"

    if factors is not None and not factors:
        return f"{header}\n✅ Alles al gelogd voor vandaag." + _dashboard_link()

    shown = factors if factors is not None else FACTORS
    lines = [header, "", _factor_list_text(shown), "", "Antwoord: /log <factor> <j/n of aantal>"]
    return "\n".join(lines) + _dashboard_link()


def route_log(session: Session, args: list[str], day: date | None = None) -> str:
    """/log <factor> <value> — record one factor for today."""
    day = _today(day)
    if len(args) < 2:
        return "Gebruik: /log <factor> <j/n of aantal>\n\n" + _factor_list_text(
            get_factors(session)
        )
    key, raw_value = args[0].lower(), args[1]
    factor = get_factor(session, key)
    if factor is None:
        return f"Onbekende factor: {key}\n\n" + _factor_list_text(get_factors(session))

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
    """/journal — show today's logged entry, or the rotated prompt if empty."""
    day = _today(day)
    entry = get_entry(session, day)
    if entry is None or not entry.responses:
        return log_prompt_text(day, factors_for_day(session, day))
    lines = [f"📓 Dagboek {_dutch_date(day)}"]
    for key, value in entry.responses.items():
        factor = get_factor(session, key)
        label = factor.label if factor else key
        shown = "ja" if value is True else "nee" if value is False else f"{value:g}"
        lines.append(f"  {label}: {shown}")
    # Still nudge the remaining questions — partial days are the norm.
    remaining = factors_for_day(session, day)
    if remaining:
        lines.append("")
        lines.append("Nog niet gelogd:")
        lines.append(_factor_list_text(remaining))
    return "\n".join(lines) + _dashboard_link()


def build_reminder_text(session: Session, day: date | None = None) -> str:
    """Evening reminder: only the rotated subset of factors for `day`."""
    day = _today(day)
    return log_prompt_text(day, factors_for_day(session, day))


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
    return "\n".join(lines) + _dashboard_link("/insights")


def build_weekly_digest(session: Session, end: date | None = None) -> str | None:
    """Weekly Signal digest text, or None if there is nothing gated to report."""
    end = _today(end)
    insights = compute_all_insights(session, end=end)
    if not insights:
        return None
    lines = [f"📈 Wekelijkse inzichten — t/m {_dutch_date(end)}"]
    for insight in insights[:5]:
        lines.append("• " + insight.text())
    return "\n".join(lines) + _dashboard_link("/insights")


__all__ = [
    "build_reminder_text",
    "build_weekly_digest",
    "log_prompt_text",
    "route_insights",
    "route_journal",
    "route_log",
]
