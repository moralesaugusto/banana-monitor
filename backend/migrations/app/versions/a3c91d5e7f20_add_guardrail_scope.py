"""guardrails get a scope: default (custom and host-inspection tools) or all tools

Existing rules keep the behaviour they always had, so nothing that works today starts blocking.

Revision ID: a3c91d5e7f20
Revises: f7081922b3c4
Create Date: 2026-11-14

"""

import sqlalchemy as sa
from alembic import op

revision = "a3c91d5e7f20"
down_revision = "f7081922b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_guardrails") as batch:
        batch.add_column(sa.Column("applies_to", sa.String(), nullable=False, server_default="default"))


def downgrade() -> None:
    with op.batch_alter_table("ai_guardrails") as batch:
        batch.drop_column("applies_to")
