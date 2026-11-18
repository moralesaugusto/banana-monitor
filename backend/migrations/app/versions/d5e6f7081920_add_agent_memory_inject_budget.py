"""add agent memory inject budget

Revision ID: d5e6f7081920
Revises: c4d5e6f70819
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op

revision = "d5e6f7081920"
down_revision = "c4d5e6f70819"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.add_column(
            sa.Column("memory_max_inject_chars", sa.Integer(), nullable=False, server_default="2000")
        )
    with op.batch_alter_table("ai_agents") as batch:
        batch.add_column(
            sa.Column("memory_max_inject_chars_override", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_agents") as batch:
        batch.drop_column("memory_max_inject_chars_override")
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.drop_column("memory_max_inject_chars")
