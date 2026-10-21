"""Add reports.snapshot and ai_mode_settings.reporter_computes_deltas_seeded

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-10-19 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('reports') as batch:
        batch.add_column(sa.Column('snapshot', sa.JSON(), nullable=True))
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(
            sa.Column(
                'reporter_computes_deltas_seeded', sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('reporter_computes_deltas_seeded')
    with op.batch_alter_table('reports') as batch:
        batch.drop_column('snapshot')
