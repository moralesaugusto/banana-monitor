"""let the agents' default model and each agent choose Ollama or OpenRouter

Revision ID: b1c2d3e4f5ac
Revises: b1c2d3e4f5ab
Create Date: 2026-10-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5ac'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(
            sa.Column(
                'llm_provider',
                sa.Enum('ollama', 'openrouter', name='assistantprovider', native_enum=False),
                nullable=False,
                server_default='ollama',
            )
        )
        batch.add_column(sa.Column('llm_credential_id', sa.Integer(), nullable=True))
    with op.batch_alter_table('ai_agents') as batch:
        batch.add_column(sa.Column('provider', sa.String(), nullable=False, server_default=''))
        batch.add_column(sa.Column('credential_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.drop_column('credential_id')
        batch.drop_column('provider')
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('llm_credential_id')
        batch.drop_column('llm_provider')
