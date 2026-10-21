"""Rename the linux_ssh integration_type to generic_ssh (data only)

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5ad
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE integrations SET integration_type = 'generic_ssh' WHERE integration_type = 'linux_ssh'"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE integrations SET integration_type = 'linux_ssh' WHERE integration_type = 'generic_ssh'"))
