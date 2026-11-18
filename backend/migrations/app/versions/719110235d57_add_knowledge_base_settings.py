"""add knowledge base settings

Revision ID: 719110235d57
Revises: a3c91d5e7f20
Create Date: 2026-11-16 16:54:58.852841

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '719110235d57'
down_revision: Union[str, Sequence[str], None] = 'a3c91d5e7f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.add_column(sa.Column('knowledge_base_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('knowledge_embedding_base_url', sa.String(), nullable=False, server_default=''))
        batch.add_column(
            sa.Column(
                'knowledge_embedding_model', sa.String(), nullable=False, server_default='nomic-embed-text'
            )
        )
        batch.add_column(
            sa.Column('knowledge_collections_seeded', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        batch.drop_column('knowledge_collections_seeded')
        batch.drop_column('knowledge_embedding_model')
        batch.drop_column('knowledge_embedding_base_url')
        batch.drop_column('knowledge_base_enabled')
