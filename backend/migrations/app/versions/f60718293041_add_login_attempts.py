"""persist failed-login counts

Revision ID: f60718293041
Revises: e5f607182930
Create Date: 2026-10-09 00:00:05.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f60718293041'
down_revision: Union[str, Sequence[str], None] = 'e5f607182930'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'login_attempts',
        sa.Column('client', sa.String(), primary_key=True),
        sa.Column('failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('login_attempts')
