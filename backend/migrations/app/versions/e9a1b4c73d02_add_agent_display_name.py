"""add agent display_name

Revision ID: e9a1b4c73d02
Revises: d8f3a2b61c90
Create Date: 2026-10-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9a1b4c73d02'
down_revision: Union[str, Sequence[str], None] = 'd8f3a2b61c90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.add_column(sa.Column('display_name', sa.String(), nullable=True))
    op.execute("UPDATE ai_agents SET display_name = 'Master Discoverer' WHERE name = 'discoverer'")


def downgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.drop_column('display_name')
