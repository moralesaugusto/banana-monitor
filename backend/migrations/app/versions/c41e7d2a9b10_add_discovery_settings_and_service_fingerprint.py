"""add discovery settings and service fingerprint

Revision ID: c41e7d2a9b10
Revises: 7f0da9937a93
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c41e7d2a9b10'
down_revision: Union[str, Sequence[str], None] = '7f0da9937a93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('services') as batch:
        batch.add_column(sa.Column('port', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('source', sa.String(), nullable=False, server_default='manual'))
        batch.add_column(sa.Column('fingerprint', sa.JSON(), nullable=True))
    op.create_table(
        'discovery_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nmap_enabled', sa.Boolean(), nullable=False),
        sa.Column('scan_mode', sa.String(), nullable=False),
        sa.Column('auto_interval_seconds', sa.Integer(), nullable=False),
        sa.Column('timing_template', sa.Integer(), nullable=False),
        sa.Column('host_timeout_seconds', sa.Integer(), nullable=False),
        sa.Column('max_retries', sa.Integer(), nullable=False),
        sa.Column('version_intensity', sa.Integer(), nullable=False),
        sa.Column('ai_mode_enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('discovery_settings')
    with op.batch_alter_table('services') as batch:
        batch.drop_column('fingerprint')
        batch.drop_column('source')
        batch.drop_column('port')
