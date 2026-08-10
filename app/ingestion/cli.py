"""CLI for data ingestion operations."""

from __future__ import annotations

import sys

from dotenv import load_dotenv


def main() -> int:
    """CLI entry point."""
    load_dotenv()

    args = sys.argv[1:]
    cmd = args[0] if args else "backfill"

    if cmd == "backfill":
        from .backfill import backfill_data

        days = int(args[1]) if len(args) > 1 else 7
        return backfill_data(days)

    print(f"Unknown command: {cmd}")
    print("Usage: gdash ingest [backfill [DAYS]]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
