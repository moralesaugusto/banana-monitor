"""vectors move to qdrant, drop embedding column

Revision ID: d3f8256e97e9
Revises: 79407b8e118e
Create Date: 2026-11-16 17:04:58.879413

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd3f8256e97e9'
down_revision: Union[str, Sequence[str], None] = '79407b8e118e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('knowledge_entries') as batch:
        batch.drop_column('embedding')


def downgrade() -> None:
    with op.batch_alter_table('knowledge_entries') as batch:
        batch.add_column(sa.Column('embedding', sa.JSON(), nullable=False, server_default='[]'))
