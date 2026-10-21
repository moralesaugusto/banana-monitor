"""add tunable model call timeouts and chat tool-call limit

Revision ID: b1c2d3e4f5aa
Revises: b1c2d3e4f5a9
Create Date: 2026-10-14 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5aa'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('assistant_config') as batch:
        batch.add_column(sa.Column('max_tool_iterations', sa.Integer(), nullable=False, server_default='8'))
        batch.add_column(sa.Column('llm_timeout_seconds', sa.Float(), nullable=False, server_default='120'))
    with op.batch_alter_table('ai_agents') as batch:
        batch.add_column(sa.Column('llm_timeout_seconds', sa.Float(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.drop_column('llm_timeout_seconds')
    with op.batch_alter_table('assistant_config') as batch:
        batch.drop_column('llm_timeout_seconds')
        batch.drop_column('max_tool_iterations')
