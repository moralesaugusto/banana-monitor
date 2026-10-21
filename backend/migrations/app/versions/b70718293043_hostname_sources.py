"""where a device's host name came from, and the DNS server asked for names

Revision ID: b70718293043
Revises: a60718293042
Create Date: 2026-10-09 00:00:07.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b70718293043'
down_revision: Union[str, Sequence[str], None] = 'a60718293042'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('devices') as batch:
        batch.add_column(sa.Column('hostname_source', sa.String(), nullable=True))
    # Names stored before sources existed all came from the reverse-DNS lookup.
    op.execute("UPDATE devices SET hostname_source = 'dns' WHERE hostname IS NOT NULL")
    with op.batch_alter_table('discovery_settings') as batch:
        batch.add_column(sa.Column('dns_server', sa.String(), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('discovery_settings') as batch:
        batch.drop_column('dns_server')
    with op.batch_alter_table('devices') as batch:
        batch.drop_column('hostname_source')
