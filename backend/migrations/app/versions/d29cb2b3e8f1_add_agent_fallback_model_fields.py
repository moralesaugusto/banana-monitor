"""add agent fallback model fields

Revision ID: d29cb2b3e8f1
Revises: d2f79ee3adca
Create Date: 2026-11-16 21:22:04.663371

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd29cb2b3e8f1'
down_revision: Union[str, Sequence[str], None] = 'd2f79ee3adca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.add_column(sa.Column('fallback_provider', sa.String(), nullable=False, server_default=''))
        batch.add_column(sa.Column('fallback_base_url', sa.String(), nullable=False, server_default=''))
        batch.add_column(sa.Column('fallback_model', sa.String(), nullable=False, server_default=''))
        batch.add_column(sa.Column('fallback_credential_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.drop_column('fallback_credential_id')
        batch.drop_column('fallback_model')
        batch.drop_column('fallback_base_url')
        batch.drop_column('fallback_provider')
