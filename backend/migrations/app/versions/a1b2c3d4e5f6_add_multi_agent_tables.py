"""add multi-agent tables

Revision ID: a1b2c3d4e5f6
Revises: f74b2c9d5e31
Create Date: 2026-10-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f74b2c9d5e31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_run_steps') as batch:
        batch.add_column(sa.Column('agent', sa.String(), nullable=True))
    op.create_table(
        'ai_agents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('system_prompt', sa.String(), nullable=False),
        sa.Column('model_override', sa.String(), nullable=False),
        sa.Column('temperature', sa.Float(), nullable=False),
        sa.Column('max_iterations', sa.Integer(), nullable=False),
        sa.Column('enabled_tools', sa.JSON(), nullable=False),
        sa.Column('subscribes', sa.JSON(), nullable=False),
        sa.Column('publishes', sa.JSON(), nullable=False),
        sa.Column('require_approval', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'ai_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('topic', sa.String(), nullable=False),
        sa.Column('sender', sa.String(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('correlation_id', sa.String(), nullable=False),
        sa.Column('reply_to', sa.String(), nullable=True),
        sa.Column('hops', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['ai_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_messages_run_id', 'ai_messages', ['run_id'])
    op.create_table(
        'ai_message_deliveries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('recipient', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['ai_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_message_deliveries_message_id', 'ai_message_deliveries', ['message_id'])


def downgrade() -> None:
    op.drop_table('ai_message_deliveries')
    op.drop_table('ai_messages')
    op.drop_table('ai_agents')
    with op.batch_alter_table('ai_run_steps') as batch:
        batch.drop_column('agent')
