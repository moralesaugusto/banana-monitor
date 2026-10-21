"""add agent internet kill switch

Revision ID: c7e2f94a1d58
Revises: b70718293043
Create Date: 2026-10-09 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e2f94a1d58'
down_revision: Union[str, Sequence[str], None] = 'b70718293043'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('discovery_settings') as batch:
        batch.add_column(sa.Column('agent_internet_blocked', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('discovery_settings') as batch:
        batch.drop_column('agent_internet_blocked')
