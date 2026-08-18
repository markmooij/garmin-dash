"""Phase 6: LLM coach — grounded context assembly + groundedness enforcement."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from app.coach.client import ask_coach, morning_commentary
from app.coach.context import build_context
from app.coach.grounding import find_ungrounded, is_grounded
from app.journal.entries import upsert_response


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DAY = date(2026, 8, 9)  # seeded day: recovery 71.5, strain 15.25, sleep 81, RHR 45


# ── grounding.py ──────────────────────────────────────────────────────

def test_find_ungrounded_matches_within_tolerance():
    context = "herstel=72 (green), strain=15.2, TSB=-2.9"
    assert find_ungrounded("Je herstel is 72", context) == []
    assert find_ungrounded("Strain van 15.3 vandaag", context) == []  # within 0.6 tolerance


def test_find_ungrounded_flags_invented_number():
    context = "herstel=72 (green), strain=15.2, TSB=-2.9"
    ungrounded = find_ungrounded("Je HRV was 55 en VO2max 61.4", context)
    assert 55.0 in ungrounded
    assert 61.4 in ungrounded


def test_find_ungrounded_ignores_small_safe_numbers():
    context = "herstel=72"
    assert find_ungrounded("Je hebt 1 sessie gedaan, 2 rustdagen", context) == []


def test_is_grounded_true_for_clean_reply():
    context = "herstel=72, strain=15.2"
    assert is_grounded("Herstel 72, strain 15.2, ga rustig aan.", context) is True


def test_is_grounded_false_for_hallucination():
    context = "herstel=72"
    assert is_grounded("Je VO2max is 61.4 vandaag", context) is False


# ── context.py ────────────────────────────────────────────────────────

def test_build_context_includes_trailing_window(seeded: Session):
    ctx = build_context(seeded, DAY, window_days=3)
    assert len(ctx.days) == 3
    assert ctx.days[-1]["date"] == DAY.isoformat()
    assert ctx.days[-1]["recovery_score"] == 71.5
    assert ctx.days[-1]["strain"] == 15.25
    assert ctx.days[-1]["sleep_score"] == 81.0
    assert ctx.days[-1]["rhr"] == 45.0


def test_build_context_empty_days_are_none(seeded: Session):
    ctx = build_context(seeded, DAY, window_days=3)
    # days before the seeded day have no data
    assert ctx.days[0]["recovery_score"] is None


def test_build_context_includes_journal_today(seeded: Session):
    upsert_response(seeded, DAY, "alcohol", 2.0)
    ctx = build_context(seeded, DAY, window_days=1)
    assert ctx.journal_today == {"alcohol": 2.0}


def test_build_context_no_journal_is_empty_dict(seeded: Session):
    ctx = build_context(seeded, DAY, window_days=1)
    assert ctx.journal_today == {}


def test_build_context_insights_empty_when_ungated(seeded: Session):
    ctx = build_context(seeded, DAY, window_days=1)
    assert ctx.insights == []


def test_to_prompt_text_contains_numbers(seeded: Session):
    ctx = build_context(seeded, DAY, window_days=1)
    text = ctx.to_prompt_text()
    assert "71" in text or "72" in text  # recovery rounds in display, exact in dict
    assert DAY.isoformat() in text


def test_to_prompt_text_lists_journal_and_insights(seeded: Session):
    upsert_response(seeded, DAY, "stress_hoog", True)
    ctx = build_context(seeded, DAY, window_days=1)
    text = ctx.to_prompt_text()
    assert "Hoge stress" in text
    assert "ja" in text


# ── client.py (mocked LLM) ──────────────────────────────────────────────

class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, reply_fn) -> None:
        self._reply_fn = reply_fn

    def create(self, **kwargs):
        return _FakeCompletion(self._reply_fn(kwargs))


class _FakeChat:
    def __init__(self, reply_fn) -> None:
        self.completions = _FakeCompletions(reply_fn)


class FakeClient:
    """Stand-in for openai.OpenAI with a scripted reply function."""

    def __init__(self, reply_fn) -> None:
        self.chat = _FakeChat(reply_fn)


def test_ask_coach_disabled_returns_message(seeded: Session, monkeypatch):
    monkeypatch.setattr("app.coach.client.get_client", lambda: None)
    reply = ask_coach(seeded, "Hoe gaat het?", DAY)
    assert "niet beschikbaar" in reply.lower()


def test_ask_coach_grounded_reply_passes_through(seeded: Session, monkeypatch):
    client = FakeClient(lambda kwargs: "Je herstel is 72, ga rustig aan.")  # noqa: ARG005
    monkeypatch.setattr("app.coach.client.get_client", lambda: client)
    reply = ask_coach(seeded, "Hoe gaat het?", DAY)
    assert "72" in reply


def test_ask_coach_ungrounded_reply_is_dropped(seeded: Session, monkeypatch):
    client = FakeClient(lambda kwargs: "Je VO2max is 61.4 en HRV was 88ms.")  # noqa: ARG005
    monkeypatch.setattr("app.coach.client.get_client", lambda: client)
    reply = ask_coach(seeded, "Hoe gaat het?", DAY)
    assert "kon geen betrouwbaar antwoord" in reply.lower()


def test_ask_coach_llm_error_returns_fallback(seeded: Session, monkeypatch):
    def _raise(kwargs):  # noqa: ARG001
        raise RuntimeError("connection refused")

    client = FakeClient(_raise)
    monkeypatch.setattr("app.coach.client.get_client", lambda: client)
    reply = ask_coach(seeded, "Hoe gaat het?", DAY)
    assert "kon geen betrouwbaar antwoord" in reply.lower()


def test_morning_commentary_none_when_disabled(seeded: Session, monkeypatch):
    monkeypatch.setattr("app.coach.client.get_client", lambda: None)
    assert morning_commentary(seeded, DAY) is None


def test_morning_commentary_grounded(seeded: Session, monkeypatch):
    client = FakeClient(lambda kwargs: "Herstel 72 vandaag, mooi resultaat.")  # noqa: ARG005
    monkeypatch.setattr("app.coach.client.get_client", lambda: client)
    text = morning_commentary(seeded, DAY)
    assert text is not None
    assert "72" in text


def test_morning_commentary_ungrounded_returns_none(seeded: Session, monkeypatch):
    client = FakeClient(lambda kwargs: "HRV was 999ms, uitstekend!")  # noqa: ARG005
    monkeypatch.setattr("app.coach.client.get_client", lambda: client)
    assert morning_commentary(seeded, DAY) is None


def test_get_client_disabled_returns_none():
    from app.coach.client import get_client

    assert get_client() is None  # LLM_ENABLED defaults False


def test_get_client_enabled_without_base_url_returns_none(monkeypatch):
    class _Settings:
        LLM_ENABLED = True
        LLM_BASE_URL = None
        LLM_API_KEY = None
        LLM_MODEL = "gpt-4o"

    monkeypatch.setattr("app.coach.client.get_settings", lambda: _Settings())
    from app.coach.client import get_client

    assert get_client() is None
