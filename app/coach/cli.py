"""CLI: gdash coach ask <question> (Phase 6)."""

from __future__ import annotations

import sys

from ..db import get_session


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] != "ask" or len(argv) < 2:
        print("gdash coach ask <question>")
        return 2

    from .client import ask_coach

    question = " ".join(argv[1:])
    session = get_session()
    try:
        print(ask_coach(session, question))
    finally:
        session.close()
    return 0


__all__ = ["main"]
