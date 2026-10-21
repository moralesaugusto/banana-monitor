"""release references to deleted devices and name unnamed integrations

Revision ID: b1c2d3e4f5ab
Revises: b1c2d3e4f5aa
Create Date: 2026-10-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b1c2d3e4f5ab'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MISSING = "device_id IS NOT NULL AND device_id NOT IN (SELECT id FROM devices)"


def upgrade() -> None:
    # Devices deleted before the delete route released its references left stale rows behind, which
    # stopped rediscovery from re-creating the device. Services keep existing and are re-linked by IP.
    op.execute(
        "DELETE FROM discovered_candidates WHERE candidate_type = 'device' AND resulting_device_id IS NOT NULL "
        "AND resulting_device_id NOT IN (SELECT id FROM devices)"
    )
    op.execute(f"UPDATE services SET device_id = NULL WHERE {_MISSING}")
    op.execute(f"UPDATE integration_targets SET device_id = NULL WHERE {_MISSING}")
    op.execute("UPDATE integrations SET name = integration_type WHERE trim(name) = '' AND integration_type != ''")


def downgrade() -> None:
    pass
