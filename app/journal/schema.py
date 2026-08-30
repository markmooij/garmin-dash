"""Journal factor registry.

The factor vocabulary is user-editable (add/remove/edit from the web UI),
so the *live* registry lives in the `journal_factors` table and is read
through the session-based accessors below (`get_factors`, `get_factor`).
`DEFAULT_FACTORS` is the seed list installed on first boot (and by the
alembic migration) — it is the stable vocabulary the correlation engine
was designed around.

Each factor is boolean ("did X happen today?") or a count (alcohol drinks,
stretch sessions). `/log` (Signal) and the web form both drive off the
registry, so adding a question is a one-line change here (or a click in
the "Factoren beheren" page).

Order matters: the Signal evening reminder asks only
`JOURNAL_PROMPT_FACTORS_PER_DAY` factors at a time and rotates through the
registry day by day (see `messaging.journal_commands.factors_for_day`), so
every factor still gets asked regularly without a wall-of-text prompt. The
full set is always available in the web form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from ..db.models import JournalFactor


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Factor:
    key: str
    label: str  # Dutch label, shown in Signal + web
    kind: str  # "bool" | "count"
    prompt: str  # short description for /help and the web form
    active: bool = True  # False = soft-deleted (hidden, data kept)


DEFAULT_FACTORS: list[Factor] = [
    Factor("alcohol", "Alcohol", "count", "aantal drankjes"),
    Factor("cafeine_laat", "Cafeïne laat", "bool", "koffie/cafeïne na 14:00"),
    Factor("laat_eten", "Laat gegeten", "bool", "maaltijd < 2u voor slapen"),
    Factor("stress_hoog", "Hoge stress", "bool", "subjectief stressvolle dag"),
    Factor("scherm_laat", "Scherm laat", "bool", "beeldscherm vlak voor slapen"),
    Factor("spierpijn", "Spierpijn", "bool", "spierpijn / DOMS"),
    Factor("ziek", "Ziek", "bool", "verkouden / ziekteverschijnselen"),
    Factor("sauna", "Sauna", "bool", "sauna bezocht"),
    Factor("magnesium", "Magnesium", "bool", "magnesium genomen"),
    Factor("laat_gewerkt", "Laat gewerkt", "bool", "'s avonds doorgewerkt"),
    Factor("stretchen", "Stretchen", "count", "aantal sessies (0/1/2)"),
]

# Compatibility aliases for the *default* seed registry (used by tests and
# docs). Application code must read the live registry via get_factors(session)
# so user edits (add/remove/edit) take effect.
FACTORS: list[Factor] = list(DEFAULT_FACTORS)
FACTORS_BY_KEY: dict[str, Factor] = {f.key: f for f in DEFAULT_FACTORS}

# Outcomes the insight engine correlates factors against. Both are read from
# computed_scores / sleep_sessions the *day after* the logged day by default
# (JOURNAL_OUTCOME_OFFSET_DAYS) — a factor logged for day D describes what
# happened during D; the behavioral effect shows up in the night D→D+1.
OUTCOMES = ("recovery_score", "sleep_score")

OUTCOME_LABELS = {"recovery_score": "herstel", "sleep_score": "slaap"}

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def parse_bool(raw: str) -> bool | None:
    """'j'/'ja'/'y'/'yes'/'1'/'true' → True, 'n'/'nee'/'no'/'0'/'false' → False."""
    v = raw.strip().lower()
    if v in ("j", "ja", "y", "yes", "1", "true", "waar"):
        return True
    if v in ("n", "nee", "no", "0", "false", "onwaar"):
        return False
    return None


# ── DB-backed live registry ───────────────────────────────────────────

def _to_factor(row: JournalFactor) -> Factor:
    return Factor(key=row.key, label=row.label, kind=row.kind, prompt=row.prompt, active=row.active)


def get_factors(session: Session, user_id: int = 1) -> list[Factor]:
    """Active factors in display order.

    Falls back to `DEFAULT_FACTORS` when the table has never been seeded
    (fresh DB before the migration runs) so the app never shows an empty
    journal form.
    """
    rows = session.execute(
        select(JournalFactor)
        .where(JournalFactor.user_id == user_id, JournalFactor.active.is_(True))
        .order_by(JournalFactor.sort_order, JournalFactor.id)
    ).scalars().all()
    if not rows:
        return list(DEFAULT_FACTORS)
    return [_to_factor(r) for r in rows]


def get_factor(session: Session, key: str, user_id: int = 1) -> Factor | None:
    """One factor by key (active or not — labels for history need deleted ones)."""
    row = session.execute(
        select(JournalFactor).where(
            JournalFactor.user_id == user_id, JournalFactor.key == key
        )
    ).scalar_one_or_none()
    return _to_factor(row) if row is not None else None


def seed_factors(session: Session, user_id: int = 1) -> int:
    """Idempotent: insert any DEFAULT_FACTORS whose key is missing. Returns count added."""
    existing = set(
        session.execute(
            select(JournalFactor.key).where(JournalFactor.user_id == user_id)
        ).scalars()
    )
    added = 0
    for i, f in enumerate(DEFAULT_FACTORS):
        if f.key not in existing:
            session.add(
                JournalFactor(
                    user_id=user_id,
                    key=f.key,
                    label=f.label,
                    kind=f.kind,
                    prompt=f.prompt,
                    sort_order=i,
                    active=True,
                )
            )
            added += 1
    if added:
        session.flush()
    return added


def create_factor(
    session: Session,
    key: str,
    label: str,
    kind: str,
    prompt: str,
    user_id: int = 1,
) -> Factor:
    """Add a factor (appended last). Re-activates a soft-deleted factor with
    the same key instead of colliding on the unique constraint."""
    key = (key or "").strip().lower()
    label = (label or "").strip()
    prompt = (prompt or "").strip()
    if not _KEY_RE.match(key):
        raise ValueError("key moet beginnen met een letter en alleen a-z, 0-9, _ bevatten")
    if kind not in ("bool", "count"):
        raise ValueError("kind moet 'bool' of 'count' zijn")
    if not label:
        raise ValueError("label mag niet leeg zijn")
    if not prompt:
        raise ValueError("prompt mag niet leeg zijn")

    row = session.execute(
        select(JournalFactor).where(JournalFactor.user_id == user_id, JournalFactor.key == key)
    ).scalar_one_or_none()
    if row is None:
        max_order = session.execute(
            select(func.max(JournalFactor.sort_order)).where(JournalFactor.user_id == user_id)
        ).scalar()
        row = JournalFactor(
            user_id=user_id,
            key=key,
            label=label,
            kind=kind,
            prompt=prompt,
            sort_order=(max_order or 0) + 1,
            active=True,
        )
        session.add(row)
    else:
        row.label, row.kind, row.prompt, row.active = label, kind, prompt, True
    session.flush()
    return _to_factor(row)


def update_factor(
    session: Session,
    key: str,
    *,
    label: str | None = None,
    kind: str | None = None,
    prompt: str | None = None,
    active: bool | None = None,
    user_id: int = 1,
) -> Factor | None:
    """Edit a factor's label/kind/prompt (and optionally soft-delete/restore)."""
    row = session.execute(
        select(JournalFactor).where(JournalFactor.user_id == user_id, JournalFactor.key == key)
    ).scalar_one_or_none()
    if row is None:
        return None
    if label is not None:
        label = label.strip()
        if not label:
            raise ValueError("label mag niet leeg zijn")
        row.label = label
    if kind is not None:
        if kind not in ("bool", "count"):
            raise ValueError("kind moet 'bool' of 'count' zijn")
        row.kind = kind
    if prompt is not None:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt mag niet leeg zijn")
        row.prompt = prompt
    if active is not None:
        row.active = active
    session.flush()
    return _to_factor(row)


def delete_factor(session: Session, key: str, user_id: int = 1) -> bool:
    """Soft-delete a factor (hidden from forms/reminders/insights; data kept)."""
    return update_factor(session, key, active=False, user_id=user_id) is not None


__all__ = [
    "DEFAULT_FACTORS",
    "FACTORS",
    "FACTORS_BY_KEY",
    "Factor",
    "OUTCOME_LABELS",
    "OUTCOMES",
    "create_factor",
    "delete_factor",
    "get_factor",
    "get_factors",
    "parse_bool",
    "seed_factors",
    "update_factor",
]
