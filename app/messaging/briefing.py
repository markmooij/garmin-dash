"""Morning briefing + Signal command routing (Phase 4).

All text is built from the same REST-API read models the web UI uses
(summary_for), so the numbers always match the dashboard. Pure functions
take an explicit session + date; the Signal wiring lives in `messenger.py`
and the scheduler calls `loop.run_morning_report()` / `loop.poll_commands()`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..settings import get_settings
from ..web.query import summary_for
from .journal_commands import route_insights, route_journal, route_log


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


_DUTCH_DAYS = [
    "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag",
]
_DUTCH_MONTHS = [
    "jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec",
]

_BANDS = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
_BAND_LABELS = {"green": "groen", "yellow": "geel", "red": "rood"}


def _dutch_date(day: date) -> str:
    return f"{_DUTCH_DAYS[day.weekday()]} {day.day} {_DUTCH_MONTHS[day.month - 1]}"


def _fmt(v: float | int | None, digits: int = 0) -> str:
    return "–" if v is None else f"{v:.{digits}f}"


def build_briefing(
    session: Session,
    day: date | None = None,
    *,
    with_commentary: bool = False,
    sleep_status: str | None = None,
) -> str:
    """Full /summary briefing for `day` (default: today, local time).

    `with_commentary`: append a short grounded LLM coach line (Phase 6) when
    LLM_ENABLED and LLM_MORNING_COMMENTARY are both true. Best-effort — a
    disabled/unreachable coach or an ungrounded reply silently omits the
    line rather than failing the briefing (the numeric report is the
    contract; commentary is decoration).

    `sleep_status`: how the sleep line is phrased when there is no sleep row.
    "absent" (watch didn't record sleep) says so explicitly and notes that
    recovery is computed without a sleep component; "pending" (Garmin still
    syncing) says the data hasn't arrived yet. None keeps the historical
    "geen registratie" wording for the /summary command.
    """
    if day is None:
        day = datetime.now(ZoneInfo(get_settings().TIMEZONE)).date()
    data = summary_for(session, day)
    rec = data["recovery"]
    w = data["wellness"]
    sleep = data["sleep"]

    lines: list[str] = []
    lines.append(f"📊 Garmin Dash — {_dutch_date(day)}")
    lines.append("─" * 22)

    # recovery
    if rec["score"] is not None:
        band = _BANDS.get(rec.get("band") or "", "⚪")
        comps = []
        if rec["components"].get("rhr") is not None:
            comps.append(f"RHR {_fmt(rec['components']['rhr'])}")
        if rec["components"].get("sleep") is not None:
            comps.append(f"slaap {_fmt(rec['components']['sleep'])}")
        if rec["components"].get("stress") is not None:
            comps.append(f"stress {_fmt(rec['components']['stress'])}")
        band_label = _BAND_LABELS.get(rec.get('band') or '', '?')
        lines.append(f"{band} Herstel {rec['score']:.0f}/100 ({band_label})")
        if comps:
            lines.append(f"   {' · '.join(comps)}")
        if sleep_status == "absent" and rec["components"].get("sleep") is None:
            lines.append("   (zonder slaapcomponent — geen slaap geregistreerd)")
    else:
        lines.append("⚪ Herstel: geen data")

    # strain + load balance
    lines.append(f"🏋️  Strain {_fmt(data['strain'])}/21  ·  TSB {_fmt(data['tsb'], 1)}")
    if data["ctl"] is not None or data["atl"] is not None:
        lines.append(f"   CTL {_fmt(data['ctl'], 1)} · ATL {_fmt(data['atl'], 1)}")

    # sleep
    if sleep["score"] is not None:
        total = ((sleep["total_s"] or 0) / 3600) if sleep["total_s"] else 0
        stages = []
        for key, label in (("deep_s", "diep"), ("rem_s", "rem"), ("light_s", "licht")):
            v = sleep.get(key) or 0
            if v:
                stages.append(f"{label} {v // 60:.0f}m")
        lines.append(f"😴 Slaap {sleep['score']:.0f}/100 ({total:.1f}u" + (f" · {' '.join(stages)}" if stages else "") + ")")
    elif sleep_status == "absent":
        lines.append("😴 Slaap: niet geregistreerd (watch niet gedragen?)")
    elif sleep_status == "pending":
        lines.append("😴 Slaap: nog niet gesynchroniseerd")
    else:
        lines.append("😴 Slaap: geen registratie")

    # watch-native
    bits = []
    if w["bb_most_recent"] is not None:
        bits.append(f"BB nu {w['bb_most_recent']:.0f}")
    if w["bb_at_wake"] is not None:
        bits.append(f"ontwaken {w['bb_at_wake']:.0f}")
    if data["vo2max"] is not None:
        bits.append(f"VO₂max {data['vo2max']:.1f}")
    if bits:
        lines.append("📱 " + " · ".join(bits))

    # activities
    acts = data.get("activities") or []
    if acts:
        lines.append("─" * 22)
        for a in acts[:3]:
            name = a.get("name") or a.get("type") or "activiteit"
            dur = a.get("duration_s")
            dur_txt = f" · {dur // 60:.0f}min" if dur else ""
            lines.append(f"💪 {name}{dur_txt}")

    if with_commentary:
        settings = get_settings()
        if settings.LLM_ENABLED and settings.LLM_MORNING_COMMENTARY:
            from ..coach.client import morning_commentary

            commentary = morning_commentary(session, day)
            if commentary:
                lines.append("─" * 22)
                lines.append(f"🤖 {commentary}")

    return "\n".join(lines)


def build_morning_report(
    session: Session, day: date | None = None, *, sleep_status: str | None = None
) -> tuple[str, str | None]:
    """Build the morning briefing and extract the coach advice line.

    Returns (text, commentary) where `text` is the full message that gets
    sent over Signal and `commentary` is the 🤖 advice line (without the
    emoji), or None when no commentary was generated (LLM disabled/failed).

    `sleep_status` is forwarded to build_briefing so the sleep line reflects
    whether the data is synced, absent, or still pending.
    """
    text = build_briefing(session, day, with_commentary=True, sleep_status=sleep_status)
    commentary: str | None = None
    for line in reversed(text.splitlines()):
        if line.startswith("🤖"):
            commentary = line[1:].strip()
            break
    return text, commentary


# ── command routing ────────────────────────────────────────────────────

def _recovery_text(session: Session, day: date) -> str:
    data = summary_for(session, day)
    rec = data["recovery"]
    if rec["score"] is None:
        return f"Herstel {_dutch_date(day)}: geen data"
    band = _BANDS.get(rec.get("band") or "", "⚪")
    comps = []
    for k, label in (("rhr", "RHR"), ("sleep", "slaap"), ("stress", "stress")):
        v = rec["components"].get(k)
        if v is not None:
            comps.append(f"{label} {v:.0f}")
    text = f"{band} Herstel {rec['score']:.0f}/100 ({_BAND_LABELS.get(rec.get('band') or '', '?')})"
    if comps:
        text += "\n" + " · ".join(comps)
    if rec.get("hrv_used"):
        text += "\n(HRV-basis)"
    else:
        text += "\n(fallback: RHR + slaap + stress)"
    return text


def _strain_text(session: Session, day: date) -> str:
    data = summary_for(session, day)
    text = f"🏋️  Strain {_fmt(data['strain'])}/21"
    if data["tsb"] is not None:
        text += f"\nTSB {data['tsb']:.1f} (CTL {_fmt(data['ctl'], 1)} · ATL {_fmt(data['atl'], 1)})"
    return text


def _sleep_text(session: Session, day: date) -> str:
    data = summary_for(session, day)
    s = data["sleep"]
    if s["score"] is None:
        return f"😴 Slaap {_dutch_date(day)}: geen registratie"
    total = (s["total_s"] or 0) / 3600
    text = f"😴 Slaap {s['score']:.0f}/100 ({total:.1f}u"
    if s.get("start_local"):
        text += f" · {s['start_local'][11:16]}–{s['end_local'][11:16]}"
    text += ")"
    return text


_COMMANDS: dict[str, str] = {
    "/summary": "volledig dagoverzicht",
    "/recovery": "herstel + componenten",
    "/strain": "strain + trainingsbalans",
    "/sleep": "slaapscore + tijden",
    "/log <factor> <j/n of aantal>": "dagboekfactor loggen",
    "/journal": "vandaag gelogde factoren",
    "/insights": "gated correlatie-inzichten",
    "/ask <vraag>": "vraag de coach (LLM, alleen echte cijfers)",
    "/help": "deze lijst",
}


def route_command(session: Session, text: str, day: date | None = None) -> str:
    """Route one incoming message to a reply (pure; no messaging side effects)."""
    if day is None:
        day = datetime.now(ZoneInfo(get_settings().TIMEZONE)).date()
    cmd = (text.strip().split() or [""])[0].lower()
    if cmd == "/summary":
        return build_briefing(session, day)
    if cmd == "/recovery":
        return _recovery_text(session, day)
    if cmd == "/strain":
        return _strain_text(session, day)
    if cmd == "/sleep":
        return _sleep_text(session, day)
    if cmd == "/log":
        return route_log(session, text.strip().split()[1:], day)
    if cmd == "/journal":
        return route_journal(session, day)
    if cmd == "/insights":
        return route_insights(session, day)
    if cmd == "/ask":
        from ..coach.client import ask_coach

        question = text.strip()[len(cmd):].strip()
        if not question:
            return "Gebruik: /ask <vraag>, bijv: /ask hoe ging deze week?"
        return ask_coach(session, question, day)
    if cmd in ("/help", "/start"):
        header = f"Garmin Dash — commando's (dag: {_dutch_date(day)})"
        body = "\n".join(f"{c} — {d}" for c, d in _COMMANDS.items())
        return f"{header}\n{body}"
    return (
        f"Onbekend commando: {cmd or '(leeg)'}\n"
        + "\n".join(f"{c} — {d}" for c, d in _COMMANDS.items())
    )
