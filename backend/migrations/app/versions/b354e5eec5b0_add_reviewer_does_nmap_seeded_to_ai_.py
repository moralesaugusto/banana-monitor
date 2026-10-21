"""Add reviewer_does_nmap_seeded to ai_mode_settings

Revision ID: b354e5eec5b0
Revises: 998679c06fb1
Create Date: 2026-10-16 21:56:31.896583

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b354e5eec5b0'
down_revision: Union[str, Sequence[str], None] = '998679c06fb1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(
            sa.Column(
                'reviewer_does_nmap_seeded', sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('reviewer_does_nmap_seeded')
