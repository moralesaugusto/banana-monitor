"""add network credential bindings

Revision ID: 7f0da9937a93
Revises: a8d72cf58024
Create Date: 2026-10-07 17:24:02.161912

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7f0da9937a93'
down_revision: Union[str, Sequence[str], None] = 'a8d72cf58024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'network_credential_bindings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('network_id', sa.Integer(), nullable=False),
        sa.Column('credential_id', sa.Integer(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['network_id'], ['networks.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('network_id', 'credential_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('network_credential_bindings')
