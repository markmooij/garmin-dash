"""raw_payloads unique(endpoint, key) — stop unbounded duplicate growth

_save_raw() used to call session.add() unconditionally, so every sync pass
that re-touched a day (the 3-day catch-up window) re-inserted the same
payload. Observed in production: 188k rows for 2.1k distinct (endpoint, key)
pairs — an 88x duplication factor, 3.9 GB of a 4.2 GB database. The app code
now upserts; this migration dedupes existing rows (keeping the most recent
`fetched_at` per key) and adds the constraint that makes a repeat impossible.

Revision ID: f6a1b8c3d9e2
Revises: e5f1a2b3c4d5
Create Date: 2026-10-06 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = 'f6a1b8c3d9e2'
down_revision: Union[str, None] = 'e5f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep only the newest row per (endpoint, key); drop the rest before the
    # constraint is added, otherwise it can't be created at all.
    op.execute(
        """
        DELETE FROM raw_payloads
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY endpoint, key
                           ORDER BY fetched_at DESC, id DESC
                       ) AS rn
                FROM raw_payloads
            )
            WHERE rn = 1
        )
        """
    )
    with op.batch_alter_table('raw_payloads', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_raw_endpoint_key', ['endpoint', 'key'])


def downgrade() -> None:
    with op.batch_alter_table('raw_payloads', schema=None) as batch_op:
        batch_op.drop_constraint('uq_raw_endpoint_key', type_='unique')
