"""Add max_run_minutes to ai_agents

Revision ID: d2e3f4a5b6c7
Revises: c1a2b3d4e5f6
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.add_column(
            sa.Column('max_run_minutes', sa.Float(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.drop_column('max_run_minutes')
