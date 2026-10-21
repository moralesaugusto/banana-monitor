"""add fingerprint to discovered_candidates

Revision ID: 84027942ae95
Revises: 0b6801186c07
Create Date: 2026-09-04 11:21:34.706611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84027942ae95'
down_revision: Union[str, Sequence[str], None] = '0b6801186c07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('discovered_candidates') as batch_op:
        batch_op.add_column(sa.Column('fingerprint', sa.String(), nullable=False, server_default=''))
        batch_op.create_unique_constraint(
            'uq_discovered_candidates_candidate_type_fingerprint', ['candidate_type', 'fingerprint']
        )
    with op.batch_alter_table('discovered_candidates') as batch_op:
        batch_op.alter_column('fingerprint', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('discovered_candidates') as batch_op:
        batch_op.drop_constraint(
            'uq_discovered_candidates_candidate_type_fingerprint', type_='unique'
        )
        batch_op.drop_column('fingerprint')
