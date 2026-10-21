"""add audit_log

Revision ID: b1c2d3e4f5a8
Revises: b1c2d3e4f5a7
Create Date: 2026-10-14 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = 'b1c2d3e4f5a8'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor', sa.String(), nullable=False),
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('status', sa.Integer(), nullable=False),
    )
    op.create_index('ix_audit_log_ts', 'audit_log', ['ts'])


def downgrade() -> None:
    op.drop_index('ix_audit_log_ts', table_name='audit_log')
    op.drop_table('audit_log')
