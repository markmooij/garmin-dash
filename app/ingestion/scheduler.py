"""Scheduled sync worker — runs the ingestion loop in the background.

Invoked via `gdash ingest schedule` or as a long-running process in the
container. Polls Garmin every SYNC_INTERVAL_MINUTES (default 15, jittered
±2 min) and syncs the last SYNC_DAYS_BACK days each pass (catch-up window
for late-arriving sleep data).
"""

from __future__ import annotations

import contextlib
import logging
import signal

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..settings import get_settings
from .sync import incremental_sync


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
    """One scheduled pass: incremental sync of the catch-up window."""
    settings = get_settings()
    days_back = int(settings.SYNC_DAYS_BACK) if settings.SYNC_DAYS_BACK else 3
    try:
        logger.info("Sync pass starting (days_back=%d)", days_back)
        incremental_sync(days_back=days_back)
        logger.info("Sync pass complete")
    except Exception:  # noqa: BLE001
        logger.exception("Sync pass failed — will retry on next interval")


def schedule() -> None:
    """Start the blocking scheduler."""
    settings = get_settings()
    interval_min = int(settings.SYNC_INTERVAL_MINUTES) if settings.SYNC_INTERVAL_MINUTES else 15
    days_back = int(settings.SYNC_DAYS_BACK) if settings.SYNC_DAYS_BACK else 3

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    scheduler = BlockingScheduler(timezone="UTC")
    _scheduler_ref.append(scheduler)
    scheduler.add_job(
        run_sync_pass,
        trigger=IntervalTrigger(minutes=interval_min, jitter=120),
        id="garmin-sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    logger.info(
        "Sync scheduler started: every %d min (±2 min jitter), days_back=%d",
        interval_min,
        days_back,
    )
    # Run once immediately so the container has data without waiting 15 min
    run_sync_pass()

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
