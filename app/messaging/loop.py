"""Messenger factory + scheduled loop (morning report, command polling)."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..db import session_scope
from ..db.models import MorningReport
from ..settings import get_settings
from ..web.query import sleep_status
from .briefing import build_morning_report, route_command
from .journal_commands import build_reminder_text, build_weekly_digest


logger = logging.getLogger("garmin_dash.messaging.loop")


def _today() -> date:
    return datetime.now(ZoneInfo(get_settings().TIMEZONE)).date()


def _parse_report_time(value: str) -> tuple[int, int]:
    """'07:30' → (7, 30); falls back to (7, 30) on garbage."""
    try:
        hour, minute = value.split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        return 7, 30


def get_messenger():
    """Build the configured Messenger, or None when Signal is disabled.

    Imported lazily so the app never hard-depends on signal_messenger
    unless it is enabled (and installed).
    """
    settings = get_settings()
    if not settings.SIGNAL_ENABLED:
        return None
    try:
        from signal_messenger import SignalRestClient
    except ImportError:  # pragma: no cover - lib missing in this environment
        logger.error("signal_messenger not installed — Signal disabled")
        return None
    if not settings.SIGNAL_CLI_API_URL or not settings.SIGNAL_ACCOUNT:
        logger.warning("SIGNAL_ENABLED=true but SIGNAL_CLI_API_URL/SIGNAL_ACCOUNT unset")
        return None
    return SignalRestClient(
        base_url=settings.SIGNAL_CLI_API_URL,
        account=settings.SIGNAL_ACCOUNT,
        token=settings.SIGNAL_CLI_TOKEN,
    )


def run_morning_report() -> str:
    """Send the daily briefing once last night's sleep is resolved.

    The briefing is deferred while sleep is still pending (Garmin lagging) and
    only sent when the sleep data has synced, or once the grace window has
    passed (the watch didn't record sleep). The briefing (and its coach advice
    line) is persisted to morning_reports before the send so the dashboard can
    show what was sent even if Signal fails; sent_at is set only on a
    successful delivery so the scheduler retries a failed send.

    Returns "sent", "pending" (sleep not resolved yet — retry later), or
    "skipped" (Signal disabled / no recipient).
    """
    settings = get_settings()
    messenger = get_messenger()
    if messenger is None:
        logger.info("Morning report skipped (Signal disabled)")
        return "skipped"
    recipient = settings.SIGNAL_RECIPIENT
    if not recipient:
        logger.warning("SIGNAL_RECIPIENT unset — morning report skipped")
        return "skipped"

    now = datetime.now(ZoneInfo(settings.TIMEZONE))
    day = now.date()

    # Don't fire before the configured report time (the cron window may start
    # earlier than the exact report minute).
    hour, minute = _parse_report_time(settings.SIGNAL_REPORT_TIME)
    report_dt = datetime.combine(day, time(hour, minute), tzinfo=now.tzinfo)
    if now < report_dt:
        logger.info(
            "Morning report: before report time (%s), deferring", settings.SIGNAL_REPORT_TIME
        )
        return "pending"

    with session_scope() as session:
        if _already_sent(session, day):
            logger.info("Morning report already sent for %s", day)
            return "sent"
        status = sleep_status(session, day, now=now)
        if status == "pending":
            logger.info("Morning report: sleep still pending for %s, deferring", day)
            return "pending"
        text, commentary = build_morning_report(session, day, sleep_status=status)
        _persist_morning_report(session, text, commentary, sent_at=None)
    try:
        messenger.send_message(recipient, text)
        logger.info("Morning report sent to %s", recipient)
        with session_scope() as session:
            _mark_sent(session, day)
    except Exception:  # noqa: BLE001
        logger.exception("Morning report send failed")
    return "sent"


def _persist_morning_report(
    session, text: str, commentary: str | None, sent_at: datetime | None = None
) -> None:
    """Upsert today's morning briefing into morning_reports (idempotent)."""
    day = _today()
    row = session.execute(
        select(MorningReport).where(
            MorningReport.user_id == 1, MorningReport.report_date == day
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(
            MorningReport(
                user_id=1,
                report_date=day,
                briefing=text,
                commentary=commentary,
                sent_at=sent_at,
            )
        )
    else:
        row.briefing = text
        row.commentary = commentary
        row.sent_at = sent_at


def _already_sent(session, day: date) -> bool:
    """True when today's briefing was actually delivered (sent_at set)."""
    row = session.execute(
        select(MorningReport).where(
            MorningReport.user_id == 1, MorningReport.report_date == day
        )
    ).scalar_one_or_none()
    return row is not None and row.sent_at is not None


def _mark_sent(session, day: date) -> None:
    """Record that today's briefing was delivered over Signal."""
    row = session.execute(
        select(MorningReport).where(
            MorningReport.user_id == 1, MorningReport.report_date == day
        )
    ).scalar_one_or_none()
    if row is not None:
        row.sent_at = datetime.now(UTC)


def run_journal_reminder() -> None:
    """Send the evening journal prompt (scheduler job at SIGNAL_JOURNAL_TIME)."""
    settings = get_settings()
    messenger = get_messenger()
    if messenger is None:
        logger.info("Journal reminder skipped (Signal disabled)")
        return
    recipient = settings.SIGNAL_RECIPIENT
    if not recipient:
        logger.warning("SIGNAL_RECIPIENT unset — journal reminder skipped")
        return
    with session_scope() as session:
        text = build_reminder_text(session)
    try:
        messenger.send_message(recipient, text)
        logger.info("Journal reminder sent to %s", recipient)
    except Exception:  # noqa: BLE001
        logger.exception("Journal reminder send failed")


def run_weekly_digest() -> None:
    """Send the weekly insights digest (scheduler job, e.g. Sunday evening).

    Silent when no factor clears the sample gate yet — the digest is not a
    nag; an empty digest every week would just get muted.
    """
    settings = get_settings()
    messenger = get_messenger()
    if messenger is None:
        logger.info("Weekly digest skipped (Signal disabled)")
        return
    recipient = settings.SIGNAL_RECIPIENT
    if not recipient:
        logger.warning("SIGNAL_RECIPIENT unset — weekly digest skipped")
        return
    with session_scope() as session:
        text = build_weekly_digest(session)
    if text is None:
        logger.info("Weekly digest skipped (no insights cleared the sample gate yet)")
        return
    try:
        messenger.send_message(recipient, text)
        logger.info("Weekly digest sent to %s", recipient)
    except Exception:  # noqa: BLE001
        logger.exception("Weekly digest send failed")


def poll_commands() -> None:
    """Poll incoming messages and answer supported commands (scheduler job)."""
    settings = get_settings()
    messenger = get_messenger()
    if messenger is None:
        return
    allowed = settings.SIGNAL_RECIPIENT
    try:
        messages = messenger.receive_messages(timeout=1)
    except Exception:  # noqa: BLE001
        logger.exception("Signal receive failed")
        return
    if messages:
        logger.info("Received %d message(s) from Signal", len(messages))
    for msg in messages:
        if allowed and msg.sender != allowed:
            logger.info("Ignoring message from unknown sender %s", msg.sender)
            continue
        if not msg.text.startswith("/"):
            logger.info("Ignoring non-command message: %r", msg.text[:60])
            continue
        with session_scope() as session:
            reply = route_command(session, msg.text)
        try:
            messenger.send_message(msg.sender, reply)
            logger.info("Answered %r for %s", msg.text, msg.sender)
        except Exception:  # noqa: BLE001
            logger.exception("Reply send failed for %s", msg.sender)
