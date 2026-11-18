"""add credential pool safeguards and per-agent credential scope

Revision ID: c4d5e6f70812
Revises: a3b4c5d6e7f8
Create Date: 2026-11-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f70812'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FLAGS = ('cred_allow_unlisted_hosts', 'cred_no_attempt_limit', 'cred_trust_new_host_keys', 'cred_pool_for_updates')


def upgrade() -> None:
    with op.batch_alter_table('ai_mode_settings') as batch:
        for flag in _FLAGS:
            batch.add_column(sa.Column(flag, sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('ai_agents') as batch:
        batch.add_column(sa.Column('credential_scope', sa.String(), nullable=False, server_default='bound'))
        batch.add_column(sa.Column('credential_scope_ids', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('ai_agents') as batch:
        batch.drop_column('credential_scope_ids')
        batch.drop_column('credential_scope')
    with op.batch_alter_table('ai_mode_settings') as batch:
        for flag in reversed(_FLAGS):
            batch.drop_column(flag)
