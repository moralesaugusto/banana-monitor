"""add per-provider LLM call concurrency caps and the form-tool seed flag to ai_mode_settings

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
Create Date: 2026-10-15 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('ollama_max_concurrent_calls', sa.Integer(), nullable=False, server_default='2'))
        batch.add_column(sa.Column('openrouter_max_concurrent_calls', sa.Integer(), nullable=False, server_default='4'))
        batch.add_column(sa.Column('form_tool_seeded', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('form_tool_seeded')
        batch.drop_column('openrouter_max_concurrent_calls')
        batch.drop_column('ollama_max_concurrent_calls')
