"""add discover_hosts scan-scope settings, and switch the AI Mode schedule interval from minutes to seconds

Revision ID: b1c2d3e4f5a6
Revises: f1a2b3c4d5e6
Create Date: 2026-10-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('allow_undefined_network_scan', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('undefined_scan_max_hosts', sa.Integer(), nullable=False, server_default='256'))
        batch.add_column(sa.Column('schedule_interval_seconds', sa.Integer(), nullable=False, server_default='21600'))
    op.execute('UPDATE ai_mode_settings SET schedule_interval_seconds = schedule_interval_minutes * 60')
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('schedule_interval_minutes')


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('schedule_interval_minutes', sa.Integer(), nullable=False, server_default='360'))
    op.execute('UPDATE ai_mode_settings SET schedule_interval_minutes = schedule_interval_seconds / 60')
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('schedule_interval_seconds')
        batch.drop_column('undefined_scan_max_hosts')
        batch.drop_column('allow_undefined_network_scan')
