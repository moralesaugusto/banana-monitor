"""add agent allow_changes and security agents seeded flag

Revision ID: d8f3a2b61c90
Revises: c7e2f94a1d58
Create Date: 2026-10-10 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8f3a2b61c90'
down_revision: Union[str, Sequence[str], None] = 'c7e2f94a1d58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.add_column(sa.Column('allow_changes', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('security_agents_seeded', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('security_agents_seeded')
    with op.batch_alter_table('ai_agents') as batch:
        batch.drop_column('allow_changes')
