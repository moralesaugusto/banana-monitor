"""add ai schedule and run time limit

Revision ID: c3d4e5f60718
Revises: b2c3d4e5f607
Create Date: 2026-10-09 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f60718'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('max_run_minutes', sa.Integer(), nullable=False, server_default='30'))
        batch.add_column(sa.Column('schedule_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('schedule_interval_minutes', sa.Integer(), nullable=False, server_default='360'))
        batch.add_column(sa.Column('schedule_entry_agent', sa.String(), nullable=False, server_default='discoverer'))
        batch.add_column(sa.Column('last_scheduled_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('schedule_cursor', sa.Integer(), nullable=False, server_default='0'))
    with op.batch_alter_table('ai_runs') as batch:
        batch.add_column(sa.Column('started_by', sa.String(), nullable=False, server_default='manual'))
        batch.add_column(sa.Column('stop_reason', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ai_runs') as batch:
        batch.drop_column('stop_reason')
        batch.drop_column('started_by')
    with op.batch_alter_table('ai_mode_settings') as batch:
        for column in ('schedule_cursor', 'last_scheduled_at', 'schedule_entry_agent',
                       'schedule_interval_minutes', 'schedule_enabled', 'max_run_minutes'):
            batch.drop_column(column)
