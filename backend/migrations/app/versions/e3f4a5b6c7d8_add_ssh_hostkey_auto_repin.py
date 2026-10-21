"""Add ssh_hostkey_auto_repin to discovery_settings

Revision ID: e3f4a5b6c7d8
Revises: d7e8f9a0b1c2
Create Date: 2026-10-15 21:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # On by default for every install, old and new: a home LAN routinely reassigns an IP to a new
    # machine (reimage, new VM), so a changed SSH host key should be re-pinned automatically rather
    # than pausing auto-login for re-approval.
    with op.batch_alter_table('discovery_settings') as batch:
        batch.add_column(
            sa.Column('ssh_hostkey_auto_repin', sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table('discovery_settings') as batch:
        batch.drop_column('ssh_hostkey_auto_repin')
