"""Journal entry storage: upsert + read (single user, user_id=1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db.models import JournalEntry


if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.orm import Session

USER_ID = 1


def get_entry(session: Session, entry_date: date, user_id: int = USER_ID) -> JournalEntry | None:
    return session.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == user_id, JournalEntry.entry_date == entry_date
        )
    ).scalar_one_or_none()


def upsert_response(
    session: Session,
    entry_date: date,
    key: str,
    value: bool | int | float,
    user_id: int = USER_ID,
) -> JournalEntry:
    """Set one factor's value for `entry_date`, creating the entry if needed.

    Merges into any existing `responses` dict for that day rather than
    replacing it — logging alcohol and stress separately on the same day
    both land in the same row.
    """
    existing = get_entry(session, entry_date, user_id)
    responses = dict(existing.responses) if existing else {}
    responses[key] = value
    if existing:
        existing.responses = responses
        session.add(existing)
        session.flush()
        return existing

    entry = JournalEntry(user_id=user_id, entry_date=entry_date, responses=responses, tags=[])
    session.add(entry)
    session.flush()
    return entry


def upsert_entry(
    session: Session,
    entry_date: date,
    responses: dict,
    tags: list[str] | None = None,
    notes: str | None = None,
    user_id: int = USER_ID,
) -> JournalEntry:
    """Replace the full entry for a day (used by the web form)."""
    stmt = sqlite_insert(JournalEntry).values(
        user_id=user_id,
        entry_date=entry_date,
        responses=responses,
        tags=tags or [],
        notes=notes,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "entry_date"],
        set_={"responses": stmt.excluded.responses, "tags": stmt.excluded.tags, "notes": stmt.excluded.notes},
    )
    session.execute(stmt)
    session.flush()
    return get_entry(session, entry_date, user_id)  # type: ignore[return-value]


def entries_in_range(
    session: Session, start: date, end: date, user_id: int = USER_ID
) -> list[JournalEntry]:
    return list(
        session.execute(
            select(JournalEntry)
            .where(
                JournalEntry.user_id == user_id,
                JournalEntry.entry_date >= start,
                JournalEntry.entry_date <= end,
            )
            .order_by(JournalEntry.entry_date)
        ).scalars()
    )
