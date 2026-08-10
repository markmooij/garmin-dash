"""CLI for data ingestion operations.

Commands:
    gdash ingest sync [DAYS_BACK]   Incremental sync (default: last 3 days)
    gdash ingest backfill [DAYS]    Full backfill (default: 90 days)
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv


def main() -> int:
    """CLI entry point."""
    load_dotenv()

    args = sys.argv[1:]
    cmd = args[0] if args else "sync"

    if cmd == "sync":
        from .sync import incremental_sync

        days = int(args[1]) if len(args) > 1 else 3
        incremental_sync(days_back=days)
        return 0

    if cmd == "backfill":
        from .sync import backfill

        days = int(args[1]) if len(args) > 1 else 90
        backfill(days)
        return 0

    if cmd == "schedule":
        from .scheduler import main as scheduler_main

        return scheduler_main()

    print(f"Unknown command: {cmd}")
    print("Usage: gdash ingest [sync [DAYS_BACK]|backfill [DAYS]|schedule]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
