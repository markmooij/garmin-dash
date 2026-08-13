"""Phase 4 prep: morning briefing text + Signal command routing (no network)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from signal_messenger import Message, Messenger

from app.messaging.briefing import build_briefing, route_command
from app.messaging.loop import poll_commands


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


def _scope(seeded: Session):
    """session_scope stand-in bound to the seeded session."""
    import contextlib

    @contextlib.contextmanager
    def scope():
        yield seeded

    return scope
