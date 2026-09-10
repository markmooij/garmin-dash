"""morning_reports.sent_at (tracks whether the briefing was actually delivered)

Revision ID: e5f1a2b3c4d5
Revises: d4f8e2a6c1b9
Create Date: 2026-09-10 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e5f1a2b3c4d5'
down_revision: Union[str, None] = 'd4f8e2a6c1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('morning_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('morning_reports', schema=None) as batch_op:
        batch_op.drop_column('sent_at')
