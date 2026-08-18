"""CLI: gdash journal today / log / insights (Phase 5)."""

from __future__ import annotations

import sys
from datetime import date

from ..db import get_session


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("gdash journal <command>")
        print("Commands: today, log <factor> <j/n of aantal> [YYYY-MM-DD], insights")
        return 2
    cmd = argv[0]

    if cmd == "today":
        from ..messaging.journal_commands import route_journal

        session = get_session()
        try:
            print(route_journal(session, date.today()))
        finally:
            session.close()
        return 0

    if cmd == "log":
        if len(argv) < 3:
            print("Gebruik: gdash journal log <factor> <j/n of aantal> [YYYY-MM-DD]")
            return 2
        from ..messaging.journal_commands import route_log

        day = date.fromisoformat(argv[3]) if len(argv) > 3 else date.today()
        session = get_session()
        try:
            print(route_log(session, argv[1:3], day))
        finally:
            session.close()
        return 0

    if cmd == "insights":
        from ..messaging.journal_commands import route_insights

        session = get_session()
        try:
            print(route_insights(session, date.today()))
        finally:
            session.close()
        return 0

    print(f"Unknown journal command: {cmd}")
    return 2


__all__ = ["main"]
