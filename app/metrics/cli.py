"""CLI: gdash metrics compute / gdash report today|weekly|monthly."""

from __future__ import annotations

import sys
from datetime import date

from ..db import get_session


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("gdash metrics <command>")
        print("Commands: compute [DAYS], backfill-from-scratch")
        return 2
    cmd = argv[0]

    if cmd == "compute":
        from .compute import compute_recent

        days = int(argv[1]) if len(argv) > 1 else 92
        results = compute_recent(days=days)
        print(f"✅ Computed {len(results)} days of scores")
        return 0

    print(f"Unknown metrics command: {cmd}")
    return 2


def report_main(argv: list[str] | None = None) -> int:
    """gdash report today|weekly|monthly."""
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("gdash report <today|weekly|monthly>")
        return 2
    cmd = argv[0]
    session = get_session()
    try:
        from .report import report_range, report_today

        today = date.today()
        if cmd == "today":
            print(report_today(session, today))
        elif cmd == "weekly":
            print(report_range(session, 7, "Weekly summary", today))
        elif cmd == "monthly":
            print(report_range(session, 30, "Monthly summary", today))
        else:
            print(f"Unknown report command: {cmd}")
            return 2
        return 0
    finally:
        session.close()
