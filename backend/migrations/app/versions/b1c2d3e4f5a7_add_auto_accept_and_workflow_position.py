"""add auto_accept_services and agent workflow position

Revision ID: b1c2d3e4f5a7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-14 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a7'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('discovery_settings') as batch:
        batch.add_column(sa.Column('auto_accept_services', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('ai_agents') as batch:
        batch.add_column(sa.Column('workflow_x', sa.Float(), nullable=True))
        batch.add_column(sa.Column('workflow_y', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.drop_column('workflow_y')
        batch.drop_column('workflow_x')
    with op.batch_alter_table('discovery_settings') as batch:
        batch.drop_column('auto_accept_services')
