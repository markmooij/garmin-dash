"""CLI entry point for the Garmin Dash application.

Subcommands are imported lazily so a failure in one module cannot break the others.
"""

from __future__ import annotations

import sys


USAGE = """Garmin Dash CLI

Usage: gdash <command> [args]

Commands:
  auth [status|start|code <CODE>]   Garmin authentication
  ingest [sync|backfill|schedule]   Data ingestion
  metrics [compute [DAYS]]          Metrics engine (compute scores)
  report [today|weekly|monthly]     Metrics reports
  journal [today|log|insights]      Journal (Phase 5)
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
    elif command == "metrics":
        from .metrics.cli import main as run
    elif command == "report":
        from .metrics.cli import report_main as run
    elif command == "journal":
        from .journal.cli import main as run
    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        return 2

    return run() or 0


if __name__ == "__main__":
    raise SystemExit(main())
