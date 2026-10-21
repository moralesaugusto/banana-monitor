"""Add cross_agent_subscriptions_seeded to ai_mode_settings

Revision ID: c1a2b3d4e5f6
Revises: b354e5eec5b0
Create Date: 2026-10-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b354e5eec5b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(
            sa.Column(
                'cross_agent_subscriptions_seeded', sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('cross_agent_subscriptions_seeded')
