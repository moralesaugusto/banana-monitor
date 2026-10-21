"""add reports, telegram config and the reporter agent

Revision ID: d4e5f6071829
Revises: c3d4e5f60718
Create Date: 2026-10-09 00:00:03.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.domain.bootstrap import REPORTER_PROMPT, REPORTER_TOOLS


revision: str = 'd4e5f6071829'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f60718'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False, server_default='snapshot'),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'telegram_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('credential_id', sa.Integer(), nullable=True),
        sa.Column('chat_ids', sa.JSON(), nullable=False),
        sa.Column('notify_alerts', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_update_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    # An install that already has agents gets the reporter now; a fresh install is seeded with all three
    # agents on first use (bootstrap.ensure_default_agents), which only runs while the table is empty.
    conn = op.get_bind()
    if conn.execute(sa.text('SELECT 1 FROM ai_agents LIMIT 1')).first() is not None:
        conn.execute(
            sa.text(
                'INSERT INTO ai_agents (name, role, system_prompt, base_url, model_override, temperature, '
                'max_iterations, enabled_tools, subscribes, publishes, require_approval, enabled, '
                'created_at, updated_at) VALUES (:name, :role, :prompt, \'\', \'\', 0.2, 6, :tools, :subs, '
                ':pubs, \'none\', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)'
            ),
            {
                'name': 'reporter',
                'role': 'Writes reports of the network and its services',
                'prompt': REPORTER_PROMPT,
                'tools': json.dumps(REPORTER_TOOLS),
                'subs': json.dumps(['task.reporter', 'human.reporter']),
                'pubs': json.dumps(['result.#']),
            },
        )


def downgrade() -> None:
    op.execute("DELETE FROM ai_agents WHERE name = 'reporter'")
    op.drop_table('telegram_config')
    op.drop_table('reports')
