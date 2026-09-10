"""Scheduled sync worker — runs the ingestion loop in the background.

Invoked via `gdash ingest schedule` or as a long-running process in the
container. Polls Garmin every SYNC_INTERVAL_MINUTES (default 15, jittered
±2 min), syncs the last SYNC_DAYS_BACK days each pass (catch-up window
for late-arriving sleep data), then recomputes materialized scores so the
dashboard never shows empty recovery/strain graphs.
"""

from __future__ import annotations

import contextlib
import logging
import signal
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..settings import get_settings
from .sync import incremental_sync


def _parse_report_time(value: str) -> tuple[int, int]:
    """'07:30' → (7, 30); falls back to (7, 30) on garbage."""
    try:
        hour, minute = value.split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        return 7, 30


logger = logging.getLogger("garmin_dash.ingestion.scheduler")

_stop_requested = False
_scheduler_ref: list[BlockingScheduler] = []


def _handle_stop(signum, frame):  # noqa: ARG001
    global _stop_requested
    _stop_requested = True
    logger.info("Stop signal received — shutting down gracefully.")
    for s in _scheduler_ref:
        with contextlib.suppress(Exception):  # noqa: BLE001
            s.shutdown(wait=False)


def run_sync_pass() -> None:
    """One scheduled pass: incremental sync + score recompute."""
    settings = get_settings()
    days_back = int(settings.SYNC_DAYS_BACK) if settings.SYNC_DAYS_BACK else 3
    try:
        logger.info("Sync pass starting (days_back=%d)", days_back)
        incremental_sync(days_back=days_back)
        logger.info("Sync pass complete")
    except Exception:  # noqa: BLE001
        logger.exception("Sync pass failed — will retry on next interval")
        return
    # Materialize scores so the dashboard never shows empty graphs. The web
    # layer only reads computed_scores — sync alone leaves recovery/strain
    # empty. Recompute the trailing window (≥92d covers the 90-day strain
    # calibration + 60-day recovery baseline; grows with SYNC_DAYS_BACK so
    # the first pass backfills the whole synced history). Idempotent.
    try:
        from ..metrics.compute import compute_recent

        window = max(days_back, 92)
        results = compute_recent(days=window)
        logger.info("Computed %d days of scores", len(results))
    except Exception:  # noqa: BLE001
        logger.exception(
            "Score recompute failed — dashboard may show empty graphs; "
            "run 'gdash metrics compute' manually"
        )


def run_morning_report_job() -> None:
    """Send the Signal morning briefing (no-op when Signal is disabled).

    The job is scheduled on an interval across the morning window so a
    late-arriving sleep sync is still picked up; run_morning_report() itself
    no-ops before the report time, while sleep is pending, and once the
    report has been sent.
    """
    try:
        from ..messaging.loop import run_morning_report

        status = run_morning_report()
        if status == "pending":
            logger.info("Morning report deferred (sleep pending) — will retry")
    except Exception:  # noqa: BLE001
        logger.exception("Morning report job failed")


def run_command_poll_job() -> None:
    """Answer Signal commands (no-op when Signal is disabled)."""
    try:
        from ..messaging.loop import poll_commands

        poll_commands()
    except Exception:  # noqa: BLE001
        logger.exception("Command poll job failed")


def run_journal_reminder_job() -> None:
    """Send the evening journal prompt (no-op when Signal is disabled)."""
    try:
        from ..messaging.loop import run_journal_reminder

        run_journal_reminder()
    except Exception:  # noqa: BLE001
        logger.exception("Journal reminder job failed")


def run_weekly_digest_job() -> None:
    """Send the weekly insights digest (no-op when Signal is disabled)."""
    try:
        from ..messaging.loop import run_weekly_digest

        run_weekly_digest()
    except Exception:  # noqa: BLE001
        logger.exception("Weekly digest job failed")


def schedule() -> None:
    """Start the blocking scheduler."""
    settings = get_settings()
    interval_min = int(settings.SYNC_INTERVAL_MINUTES) if settings.SYNC_INTERVAL_MINUTES else 15
    days_back = int(settings.SYNC_DAYS_BACK) if settings.SYNC_DAYS_BACK else 3

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    scheduler = BlockingScheduler(timezone=get_settings().TIMEZONE)
    _scheduler_ref.append(scheduler)
    # First pass runs immediately as a background job (next_run_time), NOT
    # synchronously before scheduler.start(): a big first sync (e.g.
    # SYNC_DAYS_BACK=365) would otherwise block startup for many minutes and
    # the Signal poll/morning-report jobs would not run during that time.
    try:
        tzinfo = ZoneInfo(settings.TIMEZONE)
    except Exception:  # noqa: BLE001 - invalid tz name; fall back to local
        tzinfo = None
    next_run = datetime.now(tzinfo) if tzinfo else datetime.now().astimezone()
    scheduler.add_job(
        run_sync_pass,
        trigger=IntervalTrigger(minutes=interval_min, jitter=120),
        id="garmin-sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=next_run,
    )

    if settings.SIGNAL_ENABLED:
        hour, minute = _parse_report_time(settings.SIGNAL_REPORT_TIME)
        grace_min = int(settings.SIGNAL_REPORT_GRACE_MINUTES) or 0
        retry_min = int(settings.SIGNAL_REPORT_RETRY_MINUTES) or 15
        # Run the morning report every `retry_min` across the morning window so
        # a late-arriving sleep sync is still picked up. The job itself no-ops
        # before the report time, while sleep is pending, and once the report
        # has been sent (see run_morning_report). The window spans the report
        # hour through the grace period.
        start_hour = hour
        end_hour = min(23, hour + max(1, (grace_min + 59) // 60))
        scheduler.add_job(
            run_morning_report_job,
            trigger=CronTrigger(hour=f"{start_hour}-{end_hour}", minute=f"*/{retry_min}"),
            id="signal-morning-report",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        poll_min = int(settings.SIGNAL_COMMAND_POLL_MINUTES) or 5
        scheduler.add_job(
            run_command_poll_job,
            trigger=IntervalTrigger(minutes=poll_min),
            id="signal-command-poll",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        journal_hour, journal_minute = _parse_report_time(settings.SIGNAL_JOURNAL_TIME)
        scheduler.add_job(
            run_journal_reminder_job,
            trigger=CronTrigger(hour=journal_hour, minute=journal_minute),
            id="signal-journal-reminder",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        digest_hour, digest_minute = _parse_report_time(settings.SIGNAL_DIGEST_TIME)
        scheduler.add_job(
            run_weekly_digest_job,
            trigger=CronTrigger(
                day_of_week=settings.SIGNAL_DIGEST_DAY, hour=digest_hour, minute=digest_minute
            ),
            id="signal-weekly-digest",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        logger.info(
            "Signal jobs scheduled: report %02d:%02d, command poll every %d min, "
            "journal reminder %02d:%02d, weekly digest %s %02d:%02d",
            hour,
            minute,
            poll_min,
            journal_hour,
            journal_minute,
            settings.SIGNAL_DIGEST_DAY,
            digest_hour,
            digest_minute,
        )
    else:
        logger.info("Signal disabled — no morning report / command polling")

    logger.info(
        "Sync scheduler started: every %d min (±2 min jitter), days_back=%d",
        interval_min,
        days_back,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Scheduler stopped")


def main() -> int:
    """CLI entry: gdash ingest schedule."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    schedule()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
