"""Phase 4 prep: morning briefing text + Signal command routing (no network)."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from signal_messenger import Message, Messenger

from app.journal.entries import get_entry, upsert_response
from app.journal.schema import FACTORS
from app.messaging.briefing import build_briefing, build_morning_report, route_command
from app.messaging.journal_commands import (
    build_reminder_text,
    build_weekly_digest,
    log_prompt_text,
)
from app.messaging.loop import (
    poll_commands,
    run_journal_reminder,
    run_morning_report,
    run_weekly_digest,
)


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
    # Freeze to a day whose date doesn't contain "11", so the "no nag line"
    # assertion below isn't tripped by the header date (e.g. "11 sep").
    _freeze(monkeypatch, datetime(2026, 8, 9, 20, 30, tzinfo=ZoneInfo("Europe/Amsterdam")))
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


# ── morning report persistence (dashboard "Ochtendadvies" card) ────────

class _ReportSettings:
    """Settings stub for the morning-report tests (sleep gating included)."""

    SIGNAL_RECIPIENT = "+31600000000"
    SIGNAL_REPORT_TIME = "07:30"
    SIGNAL_REPORT_GRACE_MINUTES = 180
    TIMEZONE = "Europe/Amsterdam"
    LLM_ENABLED = False
    LLM_MORNING_COMMENTARY = False


def _freeze(monkeypatch, moment: datetime):
    """Pin datetime.now() inside loop.py, query.py and journal_commands.py."""

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment

    monkeypatch.setattr("app.messaging.loop.datetime", _DT)
    monkeypatch.setattr("app.web.query.datetime", _DT)
    monkeypatch.setattr("app.messaging.journal_commands.datetime", _DT)


def _wire_report(monkeypatch, session: Session, messenger):
    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: messenger)
    monkeypatch.setattr("app.messaging.loop.get_settings", lambda: _ReportSettings())
    monkeypatch.setattr("app.messaging.loop.session_scope", _scope(session))
    monkeypatch.setattr("app.web.query.get_settings", lambda: _ReportSettings())
    monkeypatch.setattr("app.messaging.briefing.get_settings", lambda: _ReportSettings())


def test_build_morning_report_extracts_commentary(seeded: Session, monkeypatch):
    class _Settings:
        TIMEZONE = "Europe/Amsterdam"
        LLM_ENABLED = True
        LLM_MORNING_COMMENTARY = True

    monkeypatch.setattr("app.messaging.briefing.get_settings", lambda: _Settings())
    monkeypatch.setattr(
        "app.coach.client.morning_commentary", lambda session, day: "Mooi herstel!"  # noqa: ARG005
    )
    text, commentary = build_morning_report(seeded, DAY)
    assert "🤖 Mooi herstel!" in text  # full message still carries the line
    assert commentary == "Mooi herstel!"  # emoji stripped for the dashboard card


def test_build_morning_report_commentary_none_when_llm_disabled(
    seeded: Session, monkeypatch
):
    class _Settings:
        TIMEZONE = "Europe/Amsterdam"
        LLM_ENABLED = False
        LLM_MORNING_COMMENTARY = True

    monkeypatch.setattr("app.messaging.briefing.get_settings", lambda: _Settings())
    text, commentary = build_morning_report(seeded, DAY)
    assert commentary is None
    assert "Herstel" in text  # the numeric briefing is still produced


def test_run_morning_report_persists_briefing_and_commentary(
    seeded: Session, monkeypatch
):
    """The sent briefing is stored so the dashboard can show the advice."""
    from app.db.models import MorningReport

    class _Settings(_ReportSettings):
        LLM_ENABLED = True
        LLM_MORNING_COMMENTARY = True

    m = FakeMessenger()
    # DAY has seeded sleep, so the report is not deferred.
    _freeze(monkeypatch, datetime(2026, 8, 9, 7, 35, tzinfo=ZoneInfo("Europe/Amsterdam")))
    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: m)
    monkeypatch.setattr("app.messaging.loop.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.loop.session_scope", _scope(seeded))
    monkeypatch.setattr("app.web.query.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.briefing.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.settings.get_settings", lambda: _Settings())
    monkeypatch.setattr(
        "app.coach.client.morning_commentary", lambda session, day: "Rustig aan vandaag."  # noqa: ARG005
    )
    run_morning_report()

    assert len(m.sent) == 1  # still sent over Signal
    rows = seeded.query(MorningReport).all()
    assert len(rows) == 1
    assert rows[0].commentary == "Rustig aan vandaag."
    assert "Herstel" in rows[0].briefing  # full message persisted too
    assert rows[0].briefing == m.sent[0][1]  # exactly what was sent


def test_run_morning_report_persist_is_idempotent_per_day(
    seeded: Session, monkeypatch
):
    """Re-building on the same day updates the row instead of duplicating it."""
    from app.db.models import MorningReport

    class _Settings(_ReportSettings):
        LLM_ENABLED = True
        LLM_MORNING_COMMENTARY = True

    m = FakeMessenger()
    _freeze(monkeypatch, datetime(2026, 8, 9, 7, 35, tzinfo=ZoneInfo("Europe/Amsterdam")))
    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: m)
    monkeypatch.setattr("app.messaging.loop.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.loop.session_scope", _scope(seeded))
    monkeypatch.setattr("app.web.query.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.briefing.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.settings.get_settings", lambda: _Settings())

    monkeypatch.setattr(
        "app.coach.client.morning_commentary", lambda session, day: "Eerste advies."  # noqa: ARG005
    )
    run_morning_report()
    # Clear the delivery marker so the second call rebuilds rather than no-ops
    # (a real re-send happens after a failed delivery).
    seeded.query(MorningReport).one().sent_at = None
    seeded.commit()
    monkeypatch.setattr(
        "app.coach.client.morning_commentary", lambda session, day: "Tweede advies."  # noqa: ARG005
    )
    run_morning_report()

    rows = seeded.query(MorningReport).all()
    assert len(rows) == 1  # one row per day, not two
    assert rows[0].commentary == "Tweede advies."  # latest wins


def test_run_morning_report_persists_even_when_send_fails(
    seeded: Session, monkeypatch
):
    """A transient Signal failure must not lose the advice."""
    from app.db.models import MorningReport

    class _Settings(_ReportSettings):
        LLM_ENABLED = True
        LLM_MORNING_COMMENTARY = True

    class _FailingMessenger(FakeMessenger):
        def send_message(self, recipient: str, text: str) -> str | None:  # noqa: ARG002
            raise RuntimeError("signal down")

    _freeze(monkeypatch, datetime(2026, 8, 9, 7, 35, tzinfo=ZoneInfo("Europe/Amsterdam")))
    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: _FailingMessenger())
    monkeypatch.setattr("app.messaging.loop.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.loop.session_scope", _scope(seeded))
    monkeypatch.setattr("app.web.query.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.messaging.briefing.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.settings.get_settings", lambda: _Settings())
    monkeypatch.setattr(
        "app.coach.client.morning_commentary", lambda session, day: "Toch bewaard."  # noqa: ARG005
    )
    run_morning_report()  # must not raise

    rows = seeded.query(MorningReport).all()
    assert len(rows) == 1
    assert rows[0].commentary == "Toch bewaard."
    assert rows[0].sent_at is None  # delivery failed, so not marked sent


def test_run_morning_report_noop_when_signal_disabled(seeded: Session, monkeypatch):
    from app.db.models import MorningReport

    monkeypatch.setattr("app.messaging.loop.get_messenger", lambda: None)
    run_morning_report()  # must not raise
    assert seeded.query(MorningReport).all() == []  # nothing persisted


# ── sleep-gated morning report ───────────────────────────────────

def test_sleep_status_synced_when_row_exists(seeded: Session, monkeypatch):
    """A stored SleepSession means the data is in — report may go out."""
    from app.web.query import sleep_status

    monkeypatch.setattr("app.web.query.get_settings", lambda: _ReportSettings())
    tz = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 8, 9, 7, 30, tzinfo=tz)
    assert sleep_status(seeded, DAY, now=now) == "synced"


def test_sleep_status_pending_inside_grace_window(seeded: Session, monkeypatch):
    """No sleep row yet, still early: Garmin may just be lagging behind."""
    from app.web.query import sleep_status

    monkeypatch.setattr("app.web.query.get_settings", lambda: _ReportSettings())
    tz = ZoneInfo("Europe/Amsterdam")
    missing = date(2026, 8, 10)  # no SleepSession seeded for this day
    now = datetime(2026, 8, 10, 7, 30, tzinfo=tz)  # exactly at report time
    assert sleep_status(seeded, missing, now=now) == "pending"


def test_sleep_status_absent_after_grace_window(seeded: Session, monkeypatch):
    """Past the grace window the watch simply didn't record sleep."""
    from app.web.query import sleep_status

    monkeypatch.setattr("app.web.query.get_settings", lambda: _ReportSettings())
    tz = ZoneInfo("Europe/Amsterdam")
    missing = date(2026, 8, 10)
    now = datetime(2026, 8, 10, 10, 31, tzinfo=tz)  # 07:30 + 180min + 1
    assert sleep_status(seeded, missing, now=now) == "absent"


def test_sleep_status_absent_immediately_when_grace_is_zero(
    seeded: Session, monkeypatch
):
    """Grace 0 opts out of waiting entirely (old behaviour)."""
    from app.web.query import sleep_status

    class _NoGrace(_ReportSettings):
        SIGNAL_REPORT_GRACE_MINUTES = 0

    monkeypatch.setattr("app.web.query.get_settings", lambda: _NoGrace())
    tz = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 8, 10, 7, 30, tzinfo=tz)
    assert sleep_status(seeded, date(2026, 8, 10), now=now) == "absent"


def test_morning_report_defers_while_sleep_pending(seeded: Session, monkeypatch):
    """The whole point: no Ochtendadvies before the sleep data has landed."""
    from app.db.models import MorningReport

    m = FakeMessenger()
    # 2026-08-10 has no SleepSession; 07:35 is inside the grace window
    _freeze(monkeypatch, datetime(2026, 8, 10, 7, 35, tzinfo=ZoneInfo("Europe/Amsterdam")))
    _wire_report(monkeypatch, seeded, m)

    status = run_morning_report()

    assert status == "pending"
    assert m.sent == []  # nothing sent
    assert seeded.query(MorningReport).all() == []  # nothing persisted either


def test_morning_report_sends_once_sleep_has_synced(seeded: Session, monkeypatch):
    """Sleep row present → the report goes out with the real numbers."""
    from app.db.models import MorningReport

    m = FakeMessenger()
    # DAY (2026-08-09) has a seeded SleepSession with score 81
    _freeze(monkeypatch, datetime(2026, 8, 9, 7, 35, tzinfo=ZoneInfo("Europe/Amsterdam")))
    _wire_report(monkeypatch, seeded, m)

    status = run_morning_report()

    assert status == "sent"
    assert len(m.sent) == 1
    assert "Slaap 81/100" in m.sent[0][1]
    row = seeded.query(MorningReport).one()
    assert row.sent_at is not None  # delivery recorded


def test_morning_report_sends_after_grace_with_absent_note(
    seeded: Session, monkeypatch
):
    """Past the grace window it sends anyway, stating sleep wasn't recorded."""
    m = FakeMessenger()
    _freeze(monkeypatch, datetime(2026, 8, 10, 10, 45, tzinfo=ZoneInfo("Europe/Amsterdam")))
    _wire_report(monkeypatch, seeded, m)

    status = run_morning_report()

    assert status == "sent"
    assert len(m.sent) == 1
    text = m.sent[0][1]
    assert "niet geregistreerd" in text  # explicit about the missing night
    assert "nog niet gesynchroniseerd" not in text  # not the lagging wording


def test_morning_report_not_sent_twice_on_the_same_day(seeded: Session, monkeypatch):
    """The retry cadence must not spam: sent_at gates repeat sends."""
    m = FakeMessenger()
    _freeze(monkeypatch, datetime(2026, 8, 9, 7, 35, tzinfo=ZoneInfo("Europe/Amsterdam")))
    _wire_report(monkeypatch, seeded, m)

    assert run_morning_report() == "sent"
    assert run_morning_report() == "sent"  # retry tick
    assert run_morning_report() == "sent"

    assert len(m.sent) == 1  # delivered exactly once


def test_morning_report_retries_after_failed_send(seeded: Session, monkeypatch):
    """A Signal outage leaves sent_at NULL so the next tick retries."""
    from app.db.models import MorningReport

    class _FailOnce(FakeMessenger):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def send_message(self, recipient: str, text: str) -> str | None:
            if self.fail:
                self.fail = False
                raise RuntimeError("signal down")
            return super().send_message(recipient, text)

    m = _FailOnce()
    _freeze(monkeypatch, datetime(2026, 8, 9, 7, 35, tzinfo=ZoneInfo("Europe/Amsterdam")))
    _wire_report(monkeypatch, seeded, m)

    run_morning_report()  # send raises, advice still persisted
    row = seeded.query(MorningReport).one()
    assert row.sent_at is None  # not marked delivered
    assert m.sent == []

    run_morning_report()  # next scheduler tick retries
    assert len(m.sent) == 1
    seeded.refresh(row)
    assert row.sent_at is not None


def test_morning_report_waits_until_report_time(seeded: Session, monkeypatch):
    """Ticks before SIGNAL_REPORT_TIME no-op (the cron window starts earlier)."""
    m = FakeMessenger()
    _freeze(monkeypatch, datetime(2026, 8, 9, 7, 0, tzinfo=ZoneInfo("Europe/Amsterdam")))
    _wire_report(monkeypatch, seeded, m)

    assert run_morning_report() == "pending"
    assert m.sent == []


def test_briefing_sleep_wording_per_status(seeded: Session):
    """Each sleep status gets its own, unambiguous line."""
    missing = date(2026, 8, 10)
    absent = build_briefing(seeded, missing, sleep_status="absent")
    pending = build_briefing(seeded, missing, sleep_status="pending")
    plain = build_briefing(seeded, missing)

    assert "niet geregistreerd" in absent
    assert "nog niet gesynchroniseerd" in pending
    assert "geen registratie" in plain  # unchanged /summary wording


def test_briefing_absent_annotates_recovery_without_sleep(seeded: Session):
    """When sleep is genuinely missing but recovery has a score, say so."""
    from app.db.models import ComputedScore

    # A day with a recovery score computed WITHOUT a sleep component, but no
    # SleepSession row — the exact case the user reported (watch not worn).
    day = date(2026, 8, 10)
    seeded.add(ComputedScore(
        user_id=1, score_date=day,
        recovery_score=70.0, recovery_band="green",
        strain=10.0, raw_load_trimp=500.0, raw_load_edwards=40.0,
        atl=2.0, ctl=2.0, tsb=0.0,
        payload={
            "raw_load": 500.0,
            "recovery": {
                "score": 70.0, "band": "green", "hrv_used": False,
                "components": {"rhr": 60.0, "stress": 70.0},  # no sleep key
                "weights": {"rhr": 0.5, "sleep": 0.0, "stress": 0.5},
            },
            "breakdown": [],
        },
    ))
    seeded.commit()

    text = build_briefing(seeded, day, sleep_status="absent")
    assert "niet geregistreerd" in text
    assert "zonder slaapcomponent" in text  # recovery is missing its sleep part
    assert "Herstel 70/100" in text

    # When sleep is merely pending, do NOT claim it's missing from recovery.
    pending = build_briefing(seeded, day, sleep_status="pending")
    assert "zonder slaapcomponent" not in pending
    assert "nog niet gesynchroniseerd" in pending


def _scope(seeded: Session):
    """session_scope stand-in bound to the seeded session.

    Commits on exit like the real session_scope does, so code that opens a
    second scope (e.g. marking the morning report as sent after the Signal
    send) sees the first scope's writes.
    """
    import contextlib

    @contextlib.contextmanager
    def scope():
        try:
            yield seeded
            seeded.commit()
        except Exception:
            seeded.rollback()
            raise

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
