"""add llm_call_timeout_seconds to ai_mode_settings

Revision ID: f1a2b3c4d5e6
Revises: e9a1b4c73d02
Create Date: 2026-10-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e9a1b4c73d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('llm_call_timeout_seconds', sa.Float(), nullable=False, server_default='120.0'))


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('llm_call_timeout_seconds')
