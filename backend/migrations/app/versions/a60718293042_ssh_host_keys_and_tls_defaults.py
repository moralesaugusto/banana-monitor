"""SSH host key approvals, and explicit TLS settings for existing AdGuard Home / Omada integrations

Revision ID: a60718293042
Revises: f60718293041
Create Date: 2026-10-09 00:00:06.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a60718293042'
down_revision: Union[str, Sequence[str], None] = 'f60718293041'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ssh_host_keys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('host', sa.String(), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False, server_default='22'),
        sa.Column('public_key', sa.String(), nullable=False),
        sa.Column('fingerprint', sa.String(), nullable=False),
        sa.Column('approved', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('changed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('first_seen_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('host', 'port'),
    )
    # Existing installs keep auto-login as it behaved (no approval step); new installs get the row from
    # bootstrap with the approval on.
    with op.batch_alter_table('discovery_settings') as batch:
        batch.add_column(sa.Column('ssh_hostkey_approval', sa.Boolean(), nullable=False, server_default=sa.false()))

    # These two used to default to "do not verify the certificate". The default is now to verify, so an
    # integration that never said otherwise is written out explicitly, and keeps behaving as before.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, integration_type, config FROM integrations WHERE integration_type IN ('adguard_home', 'omada')")
    ).fetchall()
    for row_id, integration_type, raw in rows:
        config = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        if integration_type == 'adguard_home' and config.get('verify_tls') is True:
            config['use_https'] = True  # verify_tls=true used to be what selected https
        config.setdefault('verify_tls', False)
        conn.execute(sa.text('UPDATE integrations SET config = :c WHERE id = :i'), {'c': json.dumps(config), 'i': row_id})


def downgrade() -> None:
    with op.batch_alter_table('discovery_settings') as batch:
        batch.drop_column('ssh_hostkey_approval')
    op.drop_table('ssh_host_keys')
