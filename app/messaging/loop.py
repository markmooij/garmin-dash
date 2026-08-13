"""Messenger factory + scheduled loop (morning report, command polling)."""

from __future__ import annotations

import logging

from ..db import session_scope
from ..settings import get_settings
from .briefing import build_briefing, route_command


logger = logging.getLogger("garmin_dash.messaging.loop")


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


def run_morning_report() -> None:
    """Send the daily briefing (scheduler job at SIGNAL_REPORT_TIME)."""
    settings = get_settings()
    messenger = get_messenger()
    if messenger is None:
        logger.info("Morning report skipped (Signal disabled)")
        return
    recipient = settings.SIGNAL_RECIPIENT
    if not recipient:
        logger.warning("SIGNAL_RECIPIENT unset — morning report skipped")
        return
    with session_scope() as session:
        text = build_briefing(session)
    try:
        messenger.send_message(recipient, text)
        logger.info("Morning report sent to %s", recipient)
    except Exception:  # noqa: BLE001
        logger.exception("Morning report send failed")


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
    for msg in messages:
        if allowed and msg.sender != allowed:
            logger.info("Ignoring message from unknown sender %s", msg.sender)
            continue
        if not msg.text.startswith("/"):
            continue
        with session_scope() as session:
            reply = route_command(session, msg.text)
        try:
            messenger.send_message(msg.sender, reply)
            logger.info("Answered %r for %s", msg.text, msg.sender)
        except Exception:  # noqa: BLE001
            logger.exception("Reply send failed for %s", msg.sender)
