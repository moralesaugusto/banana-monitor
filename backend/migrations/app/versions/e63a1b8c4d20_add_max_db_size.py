"""add max_db_size_mb to discovery_settings

Revision ID: e63a1b8c4d20
Revises: d52f8a3b1c77
Create Date: 2026-10-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e63a1b8c4d20'
down_revision: Union[str, Sequence[str], None] = 'd52f8a3b1c77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('discovery_settings') as batch:
        batch.add_column(sa.Column('max_db_size_mb', sa.Integer(), nullable=False, server_default='512'))


def downgrade() -> None:
    with op.batch_alter_table('discovery_settings') as batch:
        batch.drop_column('max_db_size_mb')
