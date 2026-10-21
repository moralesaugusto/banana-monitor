"""add ai custom tools and guardrails

Revision ID: f74b2c9d5e31
Revises: e63a1b8c4d20
Create Date: 2026-10-08 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f74b2c9d5e31'
down_revision: Union[str, Sequence[str], None] = 'e63a1b8c4d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_custom_tools',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('command', sa.JSON(), nullable=False),
        sa.Column('mcp_url', sa.String(), nullable=True),
        sa.Column('mcp_tool', sa.String(), nullable=True),
        sa.Column('parameters', sa.JSON(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'ai_guardrails',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('pattern', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('ai_guardrails')
    op.drop_table('ai_custom_tools')
