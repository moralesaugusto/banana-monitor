"""add assistant tables

Revision ID: a8d72cf58024
Revises: 84027942ae95
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8d72cf58024'
down_revision: Union[str, Sequence[str], None] = '84027942ae95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'assistant_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'provider',
            sa.Enum('ollama', 'openrouter', name='assistantprovider', native_enum=False),
            nullable=False,
        ),
        sa.Column('base_url', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('credential_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'assistant_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'role', sa.Enum('user', 'assistant', name='assistantmessagerole', native_enum=False), nullable=False
        ),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('tool_calls', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('assistant_messages')
    op.drop_table('assistant_config')
