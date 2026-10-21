"""Regression tests for docs/qa/bugs.md (2026-10-14 browser QA)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_databases
from app.discovery.service import DiscoveryService
from app.domain.models import Device, DiscoveredCandidate, Service


async def _observe(ip: str = "10.0.0.7") -> int:
    return await DiscoveryService(get_databases()).record_device_observation(
        network_id=None, ip=ip, mac=None, hostname=None, open_ports=[22], via="test"
    )


async def test_a_deleted_device_is_provisioned_again_on_rediscovery(client: AsyncClient) -> None:
    first = await _observe()
    async with get_databases().app_session_factory() as session:
        session.add(Service(device_id=first, name="ssh", service_type="tcp", config={}, port=22))
        await session.commit()

    assert (await client.delete(f"/api/devices/{first}")).status_code == 204
    async with get_databases().app_session_factory() as session:
        assert (await session.scalars(select(DiscoveredCandidate))).all() == []
        assert (await session.scalars(select(Service))).one().device_id is None

    second = await _observe()
    async with get_databases().app_session_factory() as session:
        assert await session.get(Device, second) is not None


async def test_a_stale_candidate_link_is_repaired_on_observation(client: AsyncClient) -> None:
    device_id = await _observe()
    async with get_databases().app_session_factory() as session:
        await session.delete(await session.get(Device, device_id))
        await session.commit()

    new_id = await _observe()
    async with get_databases().app_session_factory() as session:
        assert await session.get(Device, new_id) is not None
        candidate = (await session.scalars(select(DiscoveredCandidate))).one()
        assert candidate.resulting_device_id == new_id


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/devices", {"display_name": "d", "device_type": "linux", "primary_ip": "999.1.1.1"}),
        ("/api/devices", {"display_name": "", "device_type": "linux"}),
        ("/api/networks", {"name": "n", "cidr": "10.0.0.0/99"}),
        ("/api/networks", {"name": "n", "cidr": "10.0.0.0/24", "vlan_id": 5000}),
        ("/api/services", {"name": "s", "service_type": "http", "config": {"url": "not a url"}}),
        ("/api/services", {"name": "s", "service_type": "tcp", "config": {"host": "h", "port": 70000}}),
        ("/api/integrations", {"integration_type": "", "name": ""}),
    ],
)
async def test_invalid_input_is_rejected(client: AsyncClient, path: str, body: dict) -> None:
    assert (await client.post(path, json=body)).status_code in (400, 422)


async def test_valid_input_is_accepted(client: AsyncClient) -> None:
    device = {"display_name": "d", "device_type": "linux", "primary_ip": "10.0.0.9"}
    assert (await client.post("/api/devices", json=device)).status_code == 201
    assert (await client.post("/api/networks", json={"name": "n", "cidr": "10.0.0.5/24"})).json()[
        "cidr"
    ] == "10.0.0.0/24"
