"""add cost budget settings

Revision ID: d2f79ee3adca
Revises: 877c8cdc0050
Create Date: 2026-11-16 20:57:21.203763

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2f79ee3adca'
down_revision: Union[str, Sequence[str], None] = '877c8cdc0050'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('cost_budget_usd', sa.Float(), nullable=True))
        batch.add_column(
            sa.Column('cost_budget_alert_sent', sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table('telegram_config') as batch:
        batch.add_column(
            sa.Column('notify_cost_budget', sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table('telegram_config') as batch:
        batch.drop_column('notify_cost_budget')
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('cost_budget_alert_sent')
        batch.drop_column('cost_budget_usd')
