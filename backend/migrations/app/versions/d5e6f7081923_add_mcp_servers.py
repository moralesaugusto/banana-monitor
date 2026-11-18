"""add ai_mcp_servers and ai_custom_tools.mcp_server_id

Revision ID: d5e6f7081923
Revises: c4d5e6f70812
Create Date: 2026-11-18 00:00:00.000000

"""
from typing import Sequence, Union
from urllib.parse import urlsplit

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7081923'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f70812'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    servers = op.create_table(
        'ai_mcp_servers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False, unique=True),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table('ai_custom_tools') as batch:
        batch.add_column(sa.Column('mcp_server_id', sa.Integer(), nullable=True))

    # Existing MCP tools (e.g. the HexStrike ones) become one server per distinct address.
    bind = op.get_bind()
    urls = [r[0] for r in bind.execute(sa.text(
        "SELECT DISTINCT mcp_url FROM ai_custom_tools WHERE kind = 'mcp' AND mcp_url IS NOT NULL"))]
    now = sa.func.current_timestamp()
    taken: set[str] = set()
    for url in urls:
        name = urlsplit(url).netloc or url
        while name in taken:
            name += '_'
        taken.add(name)
        server_id = bind.execute(
            servers.insert().values(name=name, url=url, created_at=now, updated_at=now)
        ).inserted_primary_key[0]
        bind.execute(
            sa.text("UPDATE ai_custom_tools SET mcp_server_id = :sid WHERE kind = 'mcp' AND mcp_url = :url"),
            {'sid': server_id, 'url': url},
        )


def downgrade() -> None:
    with op.batch_alter_table('ai_custom_tools') as batch:
        batch.drop_column('mcp_server_id')
    op.drop_table('ai_mcp_servers')
