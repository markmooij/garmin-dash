"""morning_reports table (persisted Signal morning briefing)

Revision ID: b3a7c9d1e5f4
Revises: 9f2c1a4b7d3e
Create Date: 2026-09-04 08:15:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b3a7c9d1e5f4'
down_revision: Union[str, None] = '9f2c1a4b7d3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'morning_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('briefing', sa.Text(), nullable=False),
        sa.Column('commentary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'report_date', name='uq_morning_user_date'),
    )
    with op.batch_alter_table('morning_reports', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_morning_reports_report_date'), ['report_date'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('morning_reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_morning_reports_report_date'))

    op.drop_table('morning_reports')
