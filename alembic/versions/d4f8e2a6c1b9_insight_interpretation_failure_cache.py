"""negative-cache failed insight interpretations

Adds `failure` and relaxes `interpretation` to NULL so a failed attempt
(LLM error or ungrounded reply) is remembered instead of being retried on
every page load — each retry cost a multi-second LLM round-trip for a
result that was dropped again.

Revision ID: d4f8e2a6c1b9
Revises: b3a7c9d1e5f4
Create Date: 2026-09-04 11:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd4f8e2a6c1b9'
down_revision: Union[str, None] = 'b3a7c9d1e5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite can't ALTER a column in place; batch mode rebuilds the table.
    with op.batch_alter_table('insight_interpretations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('failure', sa.String(length=16), nullable=True))
        batch_op.alter_column(
            'interpretation', existing_type=sa.Text(), nullable=True
        )


def downgrade() -> None:
    # Rows recording a failure have interpretation NULL and cannot satisfy the
    # restored NOT NULL — drop them before tightening the column back.
    op.execute('DELETE FROM insight_interpretations WHERE interpretation IS NULL')
    with op.batch_alter_table('insight_interpretations', schema=None) as batch_op:
        batch_op.alter_column(
            'interpretation', existing_type=sa.Text(), nullable=False
        )
        batch_op.drop_column('failure')
