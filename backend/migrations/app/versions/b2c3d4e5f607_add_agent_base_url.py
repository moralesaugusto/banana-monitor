"""add base_url to ai_agents

Revision ID: b2c3d4e5f607
Revises: a1b2c3d4e5f6
Create Date: 2026-10-09 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f607'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.add_column(sa.Column('base_url', sa.String(), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.drop_column('base_url')
