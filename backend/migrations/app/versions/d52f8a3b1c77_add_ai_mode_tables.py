"""add ai mode tables

Revision ID: d52f8a3b1c77
Revises: c41e7d2a9b10
Create Date: 2026-10-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd52f8a3b1c77'
down_revision: Union[str, Sequence[str], None] = 'c41e7d2a9b10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_mode_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('system_prompt', sa.String(), nullable=False),
        sa.Column('model_override', sa.String(), nullable=False),
        sa.Column('max_iterations', sa.Integer(), nullable=False),
        sa.Column('temperature', sa.Float(), nullable=False),
        sa.Column('max_targets', sa.Integer(), nullable=False),
        sa.Column('enabled_tools', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'ai_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('targets', sa.JSON(), nullable=False),
        sa.Column('dry_run', sa.Boolean(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('base_url', sa.String(), nullable=False),
        sa.Column('system_prompt', sa.String(), nullable=False),
        sa.Column('settings_snapshot', sa.JSON(), nullable=False),
        sa.Column('summary', sa.String(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('completion_tokens', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'ai_run_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('idx', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('request', sa.JSON(), nullable=True),
        sa.Column('response', sa.JSON(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('completion_tokens', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['ai_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_run_steps_run_id', 'ai_run_steps', ['run_id'])


def downgrade() -> None:
    op.drop_index('ix_ai_run_steps_run_id', table_name='ai_run_steps')
    op.drop_table('ai_run_steps')
    op.drop_table('ai_runs')
    op.drop_table('ai_mode_settings')
