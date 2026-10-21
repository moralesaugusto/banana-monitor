"""add the admin account and login sessions

Revision ID: e5f607182930
Revises: d4e5f6071829
Create Date: 2026-10-09 00:00:04.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f607182930'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6071829'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'admin_users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'auth_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('token_hash', sa.String(), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('auth_sessions')
    op.drop_table('admin_users')
