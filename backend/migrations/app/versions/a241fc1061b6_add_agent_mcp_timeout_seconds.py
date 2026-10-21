"""add agent mcp_timeout_seconds

Revision ID: a241fc1061b6
Revises: 1c41c0008935
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "a241fc1061b6"
down_revision = "1c41c0008935"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_agents") as batch:
        batch.add_column(sa.Column("mcp_timeout_seconds", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("ai_agents") as batch:
        batch.drop_column("mcp_timeout_seconds")
