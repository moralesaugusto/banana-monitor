"""Add maestro_merged_into_sinverguenza to ai_mode_settings

Revision ID: 998679c06fb1
Revises: 82096804df7d
Create Date: 2026-10-16 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '998679c06fb1'
down_revision: Union[str, Sequence[str], None] = '82096804df7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(
            sa.Column(
                'maestro_merged_into_sinverguenza', sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('maestro_merged_into_sinverguenza')
