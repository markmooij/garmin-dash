"""evening_reports (persisted evening wrap-up, retried until delivered)

The 23:00 wrap-up used to fire exactly once; a failed Signal send was logged
and lost. In production that dropped three nights in a row while container
networking was down, with no user-visible trace. The wrap-up is now persisted
before the send and retried until sent_at is set (or the day ends).

Revision ID: a7c3e9f1b2d4
Revises: f6a1b8c3d9e2
Create Date: 2026-10-21 10:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a7c3e9f1b2d4'
down_revision: Union[str, None] = 'f6a1b8c3d9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'evening_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('reflection', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'report_date', name='uq_evening_user_date'),
    )
    with op.batch_alter_table('evening_reports', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_evening_reports_report_date'), ['report_date'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('evening_reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_evening_reports_report_date'))
    op.drop_table('evening_reports')
