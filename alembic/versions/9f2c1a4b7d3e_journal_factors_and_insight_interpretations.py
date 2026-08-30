"""journal_factors (user-editable registry) + insight_interpretations (LLM cache)

Revision ID: 9f2c1a4b7d3e
Revises: ee3b7bb8893d
Create Date: 2026-08-21 14:30:00.000000
"""

from datetime import UTC, datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '9f2c1a4b7d3e'
down_revision: Union[str, None] = 'ee3b7bb8893d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The default seed registry (must match app/journal/schema.py::DEFAULT_FACTORS).
DEFAULT_FACTORS = [
    ("alcohol", "Alcohol", "count", "aantal drankjes"),
    ("cafeine_laat", "Cafeïne laat", "bool", "koffie/cafeïne na 14:00"),
    ("laat_eten", "Laat gegeten", "bool", "maaltijd < 2u voor slapen"),
    ("stress_hoog", "Hoge stress", "bool", "subjectief stressvolle dag"),
    ("scherm_laat", "Scherm laat", "bool", "beeldscherm vlak voor slapen"),
    ("spierpijn", "Spierpijn", "bool", "spierpijn / DOMS"),
    ("ziek", "Ziek", "bool", "verkouden / ziekteverschijnselen"),
    ("sauna", "Sauna", "bool", "sauna bezocht"),
    ("magnesium", "Magnesium", "bool", "magnesium genomen"),
    ("laat_gewerkt", "Laat gewerkt", "bool", "'s avonds doorgewerkt"),
    ("stretchen", "Stretchen", "count", "aantal sessies (0/1/2)"),
]


def upgrade() -> None:
    op.create_table('journal_factors',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('prompt', sa.String(length=200), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'key', name='uq_journal_factor_user_key')
    )

    op.create_table('insight_interpretations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('factor_key', sa.String(length=64), nullable=False),
    sa.Column('outcome_key', sa.String(length=32), nullable=False),
    sa.Column('data_hash', sa.String(length=64), nullable=False),
    sa.Column('interpretation', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'factor_key', 'outcome_key', 'data_hash', name='uq_insight_interp')
    )

    # Seed the default factor registry for the single default user (id=1).
    # The user row is guaranteed by env.py's seed_default_user() on boot.
    now = datetime.now(UTC)
    op.bulk_insert(
        sa.table(
            'journal_factors',
            sa.column('user_id', sa.Integer()),
            sa.column('key', sa.String()),
            sa.column('label', sa.String()),
            sa.column('kind', sa.String()),
            sa.column('prompt', sa.String()),
            sa.column('sort_order', sa.Integer()),
            sa.column('active', sa.Boolean()),
            sa.column('created_at', sa.DateTime()),
            sa.column('updated_at', sa.DateTime()),
        ),
        [
            {
                "user_id": 1,
                "key": key,
                "label": label,
                "kind": kind,
                "prompt": prompt,
                "sort_order": i,
                "active": True,
                "created_at": now,
                "updated_at": now,
            }
            for i, (key, label, kind, prompt) in enumerate(DEFAULT_FACTORS)
        ],
    )


def downgrade() -> None:
    op.drop_table('insight_interpretations')
    op.drop_table('journal_factors')
