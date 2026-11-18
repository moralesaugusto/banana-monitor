"""add ai agent memory

Revision ID: b3c4d5e6f708
Revises: a241fc1061b6
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op

revision = "b3c4d5e6f708"
down_revision = "a241fc1061b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_agent_memory_agent_name", "ai_agent_memory", ["agent_name"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_agent_memory_agent_name", table_name="ai_agent_memory")
    op.drop_table("ai_agent_memory")
