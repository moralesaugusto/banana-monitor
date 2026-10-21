"""Raise ai_mode_settings.max_iterations default from 15 to 30

Revision ID: 82096804df7d
Revises: f4a5b6c7d8e9
Create Date: 2026-10-16 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '82096804df7d'
down_revision: Union[str, Sequence[str], None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.alter_column('max_iterations', server_default='30')
    op.execute("UPDATE ai_mode_settings SET max_iterations = 30 WHERE max_iterations = 15")


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.alter_column('max_iterations', server_default='15')
    op.execute("UPDATE ai_mode_settings SET max_iterations = 15 WHERE max_iterations = 30")
