"""add in_agent_pool to credentials

Revision ID: b1c2d3e4f5a6
Revises: 028c5b0889b7
Create Date: 2026-11-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = '028c5b0889b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('credentials') as batch:
        batch.add_column(sa.Column('in_agent_pool', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('credentials') as batch:
        batch.drop_column('in_agent_pool')
