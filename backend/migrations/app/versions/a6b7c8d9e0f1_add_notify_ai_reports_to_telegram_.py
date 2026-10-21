"""Add notify_ai_reports to telegram_config

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-10-19 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6b7c8d9e0f1'
down_revision: Union[str, Sequence[str], None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('telegram_config') as batch:
        batch.add_column(sa.Column('notify_ai_reports', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table('telegram_config') as batch:
        batch.drop_column('notify_ai_reports')
