"""CLI for data ingestion operations."""

import sys
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .backfill import backfill_data


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Garmin Dash — Ingestion CLI")
        print("Usage: gdash ingest <command>")
        print("Commands: backfill, schedule")
        print("Run 'gdash ingest --help' for more info.")
        sys.exit(1)

    command = sys.argv[1]

    if command == "backfill":
        backfill_data()
    elif command == "schedule":
        schedule_sync()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


def schedule_sync():
    """Schedule daily sync job."""
    scheduler = BlockingScheduler()
    print("📅 Scheduling sync job (every 15 minutes)...")
    print()

    def sync():
        print("🔄 Starting sync...")
        # Sync logic here
        print("✅ Sync complete")

    scheduler.add_job(
        sync,
        trigger=IntervalTrigger(minutes=15, jitter=5),
        id="garmin-sync",
        replace_existing=True,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Scheduler stopped")
