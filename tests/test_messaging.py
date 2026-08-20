"""Phase 4 prep: morning briefing text + Signal command routing (no network)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from signal_messenger import Message, Messenger

from app.journal.entries import get_entry, upsert_response
from app.journal.schema import FACTORS
from app.messaging.briefing import build_briefing, route_command
from app.messaging.journal_commands import (
    build_reminder_text,
    build_weekly_digest,
    log_prompt_text,
)
from app.messaging.loop import poll_commands, run_journal_reminder, run_weekly_digest


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


DAY = date(2026, 8, 9)  # seeded day: recovery 71.5 green, strain 15.25, sleep 81


class FakeMessenger(Messenger):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.inbox: list[Message] = []

    def send_message(self, recipient: str, text: str) -> str | None:
        self.sent.append((recipient, text))
        return "id-1"

    def receive_messages(self, timeout: int = 10) -> list[Message]:
        del timeout  # fake: return the whole inbox at once
        return self.inbox

    def health(self) -> bool:
        return True


# ── briefing ───────────────────────────────────────────────────────────

def test_briefing_contains_seeded_values(seeded: Session):
    text = build_briefing(seeded, DAY)
    assert "Garmin Dash" in text
    assert "Herstel 72/100" in text  # 71.5 rounds to 72
    assert "🟢" in text
    assert "Strain 15/21" in text
    assert "TSB" in text
    assert "Slaap 81/100" in text
    assert "VO₂max 51.0" in text
    assert "BB nu 50" in text
    assert "ontwaken 80" in text
    assert "Kracht" in text  # seeded strength activity listed


def test_briefing_missing_day(seeded: Session):
    text = build_briefing(seeded, date(2026, 1, 1))
    assert "geen data" in text


# ── command routing ────────────────────────────────────────────────────

def test_route_summary(seeded: Session):
    reply = route_command(seeded, "/summary", DAY)
    assert "Herstel" in reply
    assert "Strain" in reply


def test_route_recovery(seeded: Session):
    reply = route_command(seeded, "/recovery", DAY)
    assert "Herstel 72/100" in reply
    assert "RHR 60" in reply
    assert "fallback" in reply  # seeded recovery is the HRV-less fallback


def test_route_strain(seeded: Session):
    reply = route_command(seeded, "/strain", DAY)
    assert "Strain 15/21" in reply
    assert "TSB" in reply


def test_route_sleep(seeded: Session):
    reply = route_command(seeded, "/sleep", DAY)
    assert "Slaap 81/100" in reply


def test_route_help_and_unknown(seeded: Session):
    reply = route_command(seeded, "/help", DAY)
    assert "/summary" in reply
    assert "commando" in reply
    reply2 = route_command(seeded, "/bogus", DAY)
    assert "Onbekend" in reply2
    assert "/help" in reply2


def test_route_case_and_whitespace(seeded: Session):
    assert "Herstel" in route_command(seeded, "  /SUMMARY  ", DAY)


# ── poll loop ──────────────────────────────────────────────────────────

def test_poll_answers_only_allowed_sender_and_commands(seeded: Session, monkeypatch):
    class _Settings:
        SIGNAL_RECIPIENT = "+31600000000"

    m = FakeMessenger()
    m.inbox = [
        Message(sender="+31600000000", text="/summary", timestamp=1),
        Message(sender="+31999999999", text="/summary", timestamp=2),  # unknown sender
        Message(sender="+31600000000", text="geen commando", timestamp=3),
    ]
    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: m)
    monkeypatch.setattr("app.messaging.loop.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.loop.session_scope", _scope(seeded))
    poll_commands()
    # only the /summary from the allowed sender is answered
    assert len(m.sent) == 1
    recipient, reply = m.sent[0]
    assert recipient == "+31600000000"
    assert "Herstel" in reply


# ── journal commands (Phase 5) ───────────────────────────────────────

def test_route_log_bool_factor(seeded: Session):
    reply = route_command(seeded, "/log stress_hoog j", DAY)
    assert "Genoteerd" in reply
    entry = get_entry(seeded, DAY)
    assert entry.responses == {"stress_hoog": True}


def test_route_log_count_factor(seeded: Session):
    reply = route_command(seeded, "/log alcohol 2", DAY)
    assert "Genoteerd" in reply
    entry = get_entry(seeded, DAY)
    assert entry.responses == {"alcohol": 2.0}


def test_route_log_merges_across_calls(seeded: Session):
    route_command(seeded, "/log alcohol 1", DAY)
    route_command(seeded, "/log ziek n", DAY)
    entry = get_entry(seeded, DAY)
    assert entry.responses == {"alcohol": 1.0, "ziek": False}


def test_route_log_unknown_factor(seeded: Session):
    reply = route_command(seeded, "/log bogus j", DAY)
    assert "Onbekende factor" in reply


def test_route_log_bad_bool_value(seeded: Session):
    reply = route_command(seeded, "/log stress_hoog maybe", DAY)
    assert "j/n" in reply
    assert get_entry(seeded, DAY) is None


def test_route_log_bad_count_value(seeded: Session):
    reply = route_command(seeded, "/log alcohol veel", DAY)
    assert "getal" in reply


def test_route_log_missing_args(seeded: Session):
    reply = route_command(seeded, "/log", DAY)
    assert "Gebruik" in reply


def test_route_journal_empty_shows_prompt(seeded: Session):
    reply = route_command(seeded, "/journal", DAY)
    assert "/log" in reply


def test_route_journal_shows_logged_entry(seeded: Session):
    route_command(seeded, "/log alcohol 2", DAY)
    reply = route_command(seeded, "/journal", DAY)
    assert "Alcohol" in reply
    assert "2" in reply


def test_route_insights_under_gate(seeded: Session):
    reply = route_command(seeded, "/insights", DAY)
    assert "Nog geen inzichten" in reply


def test_help_lists_journal_commands(seeded: Session):
    reply = route_command(seeded, "/help", DAY)
    assert "/log" in reply
    assert "/journal" in reply
    assert "/insights" in reply
    assert "/ask" in reply


# ── coach command (Phase 6) ───────────────────────────────────────

def test_route_ask_missing_question(seeded: Session):
    reply = route_command(seeded, "/ask", DAY)
    assert "Gebruik" in reply


def test_route_ask_disabled_coach(seeded: Session, monkeypatch):
    monkeypatch.setattr("app.coach.client.get_client", lambda: None)
    reply = route_command(seeded, "/ask hoe gaat het?", DAY)
    assert "niet beschikbaar" in reply.lower()


def test_build_briefing_without_commentary_by_default(seeded: Session):
    text = build_briefing(seeded, DAY)
    assert "🤖" not in text  # commentary only appended when with_commentary=True


def test_build_briefing_with_commentary_disabled_llm_is_silent(seeded: Session, monkeypatch):
    class _Settings:
        TIMEZONE = "Europe/Amsterdam"
        LLM_ENABLED = False
        LLM_MORNING_COMMENTARY = True

    monkeypatch.setattr("app.messaging.briefing.get_settings", lambda: _Settings())
    text = build_briefing(seeded, DAY, with_commentary=True)
    assert "🤖" not in text


def test_build_briefing_with_commentary_appends_grounded_line(seeded: Session, monkeypatch):
    class _Settings:
        TIMEZONE = "Europe/Amsterdam"
        LLM_ENABLED = True
        LLM_MORNING_COMMENTARY = True

    monkeypatch.setattr("app.messaging.briefing.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.coach.client.morning_commentary", lambda session, day: "Mooi herstel!")  # noqa: ARG005
    text = build_briefing(seeded, DAY, with_commentary=True)
    assert "🤖 Mooi herstel!" in text


def test_log_prompt_text_lists_all_factors():
    text = log_prompt_text(DAY)
    assert "alcohol" in text
    assert "stress_hoog" in text
    assert "sauna" in text
    assert "magnesium" in text
    assert "laat_gewerkt" in text
    assert "stretchen" in text


def test_build_weekly_digest_none_when_ungated(seeded: Session):
    assert build_weekly_digest(seeded, DAY) is None


# ── journal reminder / digest scheduler jobs ─────────────────────────

def test_run_journal_reminder_sends_prompt(seeded: Session, monkeypatch):
    class _Settings:
        SIGNAL_RECIPIENT = "+31600000000"

    m = FakeMessenger()
    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: m)
    monkeypatch.setattr("app.messaging.loop.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.loop.session_scope", _scope(seeded))
    run_journal_reminder()
    assert len(m.sent) == 1
    recipient, text = m.sent[0]
    assert recipient == "+31600000000"
    assert "/log" in text


def test_run_journal_reminder_asks_at_most_three_factors(seeded: Session, monkeypatch):
    class _Settings:
        SIGNAL_RECIPIENT = "+31600000000"

    m = FakeMessenger()
    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: m)
    monkeypatch.setattr("app.messaging.loop.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.loop.session_scope", _scope(seeded))
    run_journal_reminder()
    _recipient, text = m.sent[0]
    asked = [f.key for f in FACTORS if f"{f.key} —" in text]
    assert len(asked) == 3
    assert "11" not in text  # no nag line — the message stays minimal
    assert "Antwoord: /log" in text


def test_run_journal_reminder_noop_when_disabled(monkeypatch):
    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: None)
    run_journal_reminder()  # must not raise


def test_run_weekly_digest_skips_when_ungated(seeded: Session, monkeypatch):
    class _Settings:
        SIGNAL_RECIPIENT = "+31600000000"

    m = FakeMessenger()
    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: m)
    monkeypatch.setattr("app.messaging.loop.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.loop.session_scope", _scope(seeded))
    run_weekly_digest()
    assert m.sent == []  # nothing cleared the sample gate


def _scope(seeded: Session):
    """session_scope stand-in bound to the seeded session."""
    import contextlib

    @contextlib.contextmanager
    def scope():
        yield seeded

    return scope


# ── dashboard link in Signal messages ────────────────────────────────

def test_reminder_omits_link_when_url_unset(seeded: Session):
    text = build_reminder_text(seeded, DAY)
    assert "🔗" not in text  # DASHBOARD_URL defaults to "" — no placeholder URL


def test_reminder_includes_journal_link_when_url_set(seeded: Session, monkeypatch):
    class _Settings:
        DASHBOARD_URL = "https://dash.example.com/"
        TIMEZONE = "Europe/Amsterdam"
        JOURNAL_PROMPT_FACTORS_PER_DAY = 3
        JOURNAL_INSIGHT_WINDOW_DAYS = 90
        JOURNAL_INSIGHT_MIN_SAMPLES = 5
        JOURNAL_OUTCOME_OFFSET_DAYS = 1

    monkeypatch.setattr("app.messaging.journal_commands.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.journal.rotation.get_settings", lambda: _Settings())
    text = build_reminder_text(seeded, DAY)
    assert "https://dash.example.com/journal" in text  # trailing slash normalised


def test_reminder_says_done_when_all_logged(seeded: Session):
    for factor in FACTORS:
        upsert_response(seeded, DAY, factor.key, 1.0 if factor.kind == "count" else True)
    seeded.commit()
    text = build_reminder_text(seeded, DAY)
    assert "Alles al gelogd" in text
