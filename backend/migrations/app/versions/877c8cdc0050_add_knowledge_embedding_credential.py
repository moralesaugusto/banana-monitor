"""add knowledge embedding credential

Revision ID: 877c8cdc0050
Revises: 719110235d57
Create Date: 2026-11-16 19:17:12.000131

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '877c8cdc0050'
down_revision: Union[str, Sequence[str], None] = '719110235d57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('knowledge_embedding_credential_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('knowledge_embedding_credential_id')
