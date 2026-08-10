"""CLI entry point for the Garmin Dash application.

Subcommands are imported lazily so a failure in one module cannot break the others.
"""

from __future__ import annotations

import sys


USAGE = """Garmin Dash CLI

Usage: gdash <command> [args]

Commands:
  auth [status|start|code <CODE>]   Garmin authentication
  ingest [backfill|schedule]        Data ingestion
  report [today|weekly|monthly]     Metrics reports
"""


def main() -> int:
    """Dispatch to a subcommand."""
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0 if args else 1

    command, rest = args[0], args[1:]
    sys.argv = [f"gdash {command}", *rest]

    if command == "auth":
        from .auth.cli import main as run
    elif command == "ingest":
        from .ingestion.cli import main as run
    elif command == "report":
        from .metrics.cli import main as run
    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        return 2

    return run() or 0


if __name__ == "__main__":
    raise SystemExit(main())
