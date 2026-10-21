"""add token usage counters

Revision ID: b1c2d3e4f5ad
Revises: b1c2d3e4f5ac
Create Date: 2026-10-15 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5ad'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_usage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('day', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('agent', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('calls', sa.Integer(), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('completion_tokens', sa.Integer(), nullable=False),
        sa.Column('max_context_tokens', sa.Integer(), nullable=False),
        sa.Column('calls_without_usage', sa.Integer(), nullable=False),
        sa.UniqueConstraint('day', 'source', 'agent', 'provider', 'model'),
    )
    op.create_index('ix_llm_usage_day', 'llm_usage', ['day'])
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('usage_reset_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('usage_reset_at')
    op.drop_index('ix_llm_usage_day', table_name='llm_usage')
    op.drop_table('llm_usage')
