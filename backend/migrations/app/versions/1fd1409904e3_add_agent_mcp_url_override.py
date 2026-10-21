"""add agent mcp_url_override

Revision ID: 1fd1409904e3
Revises: b7c8d9e0f1a2
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "1fd1409904e3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_agents", sa.Column("mcp_url_override", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_agents", "mcp_url_override")
