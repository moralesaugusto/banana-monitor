"""add the agents' default LLM to ai_mode_settings

Revision ID: b1c2d3e4f5a9
Revises: b1c2d3e4f5a8
Create Date: 2026-10-14 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.config import get_settings


revision: str = 'b1c2d3e4f5a9'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(
            sa.Column('llm_base_url', sa.String(), nullable=False, server_default=get_settings().ollama_base_url)
        )
        batch.add_column(
            sa.Column('llm_model', sa.String(), nullable=False, server_default=get_settings().ollama_model)
        )
    # Agents used the chat assistant's host and model until now; keep them on it.
    op.execute(
        "UPDATE ai_mode_settings SET "
        "llm_base_url = (SELECT base_url FROM assistant_config ORDER BY id LIMIT 1), "
        "llm_model = (SELECT model FROM assistant_config ORDER BY id LIMIT 1) "
        "WHERE EXISTS (SELECT 1 FROM assistant_config)"
    )


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('llm_model')
        batch.drop_column('llm_base_url')
