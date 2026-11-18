"""add agent memory limits

Revision ID: c4d5e6f70819
Revises: b3c4d5e6f708
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op

revision = "c4d5e6f70819"
down_revision = "b3c4d5e6f708"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.add_column(
            sa.Column("memory_max_entries_per_agent", sa.Integer(), nullable=False, server_default="30")
        )
        batch.add_column(
            sa.Column("memory_max_content_chars", sa.Integer(), nullable=False, server_default="500")
        )
    with op.batch_alter_table("ai_agents") as batch:
        batch.add_column(
            sa.Column("memory_max_entries_override", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("memory_max_content_chars_override", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_agents") as batch:
        batch.drop_column("memory_max_content_chars_override")
        batch.drop_column("memory_max_entries_override")
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.drop_column("memory_max_content_chars")
        batch.drop_column("memory_max_entries_per_agent")
