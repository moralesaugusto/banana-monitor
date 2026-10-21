"""add tajonaso_seeded flag

Revision ID: 1c41c0008935
Revises: 1fd1409904e3
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "1c41c0008935"
down_revision = "1fd1409904e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.add_column(sa.Column("tajonaso_seeded", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("ai_mode_settings") as batch:
        batch.drop_column("tajonaso_seeded")
