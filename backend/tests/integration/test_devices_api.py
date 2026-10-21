import datetime

import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.discovery.reachability import INACTIVE_AFTER
from app.domain.enums import EntityType, HealthStatus
from app.domain.metrics_models import MetricSample
from app.domain.models import Device, utcnow


@pytest.mark.asyncio
async def test_create_device_and_get_detail(client: AsyncClient) -> None:
    response = await client.post(
        "/api/devices",
        json={"display_name": "pve1", "device_type": "proxmox_node", "primary_ip": "192.168.1.10"},
    )
    assert response.status_code == 201
    device = response.json()
    assert device["display_name"] == "pve1"
    assert device["status"] == "unknown"
    assert device["site_id"] == 1

    response = await client.get(f"/api/devices/{device['id']}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["addresses"] == []
    assert detail["services"] == []


@pytest.mark.asyncio
async def test_device_detail_includes_services(client: AsyncClient) -> None:
    device = (
        await client.post("/api/devices", json={"display_name": "pve1", "device_type": "proxmox_node"})
    ).json()

    await client.post(
        "/api/services",
        json={
            "name": "pve-web",
            "service_type": "https",
            "device_id": device["id"],
            "config": {"url": "https://192.168.1.10:8006"},
        },
    )

    response = await client.get(f"/api/devices/{device['id']}")
    assert response.status_code == 200
    services = response.json()["services"]
    assert len(services) == 1
    assert services[0]["name"] == "pve-web"


@pytest.mark.asyncio
async def test_update_and_delete_device(client: AsyncClient) -> None:
    device = (
        await client.post("/api/devices", json={"display_name": "pve1", "device_type": "proxmox_node"})
    ).json()

    response = await client.patch(f"/api/devices/{device['id']}", json={"managed": False})
    assert response.status_code == 200
    assert response.json()["managed"] is False

    response = await client.delete(f"/api/devices/{device['id']}")
    assert response.status_code == 204

    response = await client.get(f"/api/devices/{device['id']}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_device_detail_and_history_include_metrics(client: AsyncClient) -> None:
    device = (
        await client.post("/api/devices", json={"display_name": "pve1", "device_type": "proxmox_node"})
    ).json()

    databases = get_databases()
    async with databases.metrics_session_factory() as session:
        session.add(
            MetricSample(
                entity_type=EntityType.DEVICE, entity_id=device["id"], metric_name="load1", value=0.42
            )
        )
        await session.commit()

    response = await client.get(f"/api/devices/{device['id']}")
    assert response.json()["metrics"] == {"load1": 0.42}

    response = await client.get(f"/api/devices/{device['id']}/metrics/load1")
    assert response.status_code == 200
    points = response.json()
    assert len(points) == 1
    assert points[0]["value"] == 0.42


@pytest.mark.asyncio
async def test_rescan_device_fingerprints_open_ports(client: AsyncClient) -> None:
    from unittest.mock import AsyncMock, patch

    body = {"display_name": "box", "device_type": "other", "primary_ip": "10.0.0.9"}
    device = (await client.post("/api/devices", json=body)).json()
    found = {22: {"name": "ssh", "product": "OpenSSH"}}
    with (
        patch("app.discovery.rescan.tcp_ports.scan_ports", AsyncMock(return_value=[22])),
        patch("app.discovery.rescan.nmap_scan.fingerprint_services", AsyncMock(return_value=found)),
    ):
        response = await client.post(f"/api/devices/{device['id']}/rescan")
    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    services = (await client.get(f"/api/services?device_id={device['id']}")).json()
    assert services[0]["fingerprint"]["product"] == "OpenSSH"


@pytest.mark.asyncio
async def test_rescan_device_sweeps_every_port_but_a_single_port_rescan_stays_narrow(
    client: AsyncClient,
) -> None:
    from unittest.mock import AsyncMock, patch

    from app.db.session import get_databases
    from app.discovery.rescan import rescan_device

    body = {"display_name": "b", "device_type": "other", "primary_ip": "10.0.0.8"}
    device = (await client.post("/api/devices", json=body)).json()
    sweep = AsyncMock(return_value=[])
    with patch("app.discovery.rescan.tcp_ports.scan_ports", sweep):
        await client.post(f"/api/devices/{device['id']}/rescan")
        assert set(sweep.call_args.args[1]) == set(range(1, 65536))

        await rescan_device(get_databases(), device["id"], only_port=2222)
        assert sweep.call_args.args[1] == [2222]


@pytest.mark.asyncio
async def test_rescan_device_without_ip_conflicts(client: AsyncClient) -> None:
    device = (await client.post("/api/devices", json={"display_name": "x", "device_type": "other"})).json()
    assert (await client.post(f"/api/devices/{device['id']}/rescan")).status_code == 409


@pytest.mark.asyncio
async def test_list_devices_infers_role_and_counts_services(client: AsyncClient) -> None:
    body = {"display_name": "mystery", "device_type": "other", "primary_ip": "10.0.0.7"}
    device = (await client.post("/api/devices", json=body)).json()
    service = {"name": "x", "service_type": "tcp", "device_id": device["id"]}
    await client.post("/api/services", json={**service, "config": {"host": "10.0.0.7", "port": 1}})
    row = (await client.get("/api/devices")).json()[0]
    assert row["service_count"] == 1
    assert row["role"] == "Unclassified"


@pytest.mark.asyncio
async def test_a_device_down_and_unseen_for_long_enough_is_marked_inactive(client: AsyncClient) -> None:
    device = (
        await client.post(
            "/api/devices", json={"display_name": "old", "device_type": "other", "primary_ip": "10.0.0.9"}
        )
    ).json()
    assert device["inactive"] is False  # unknown status: never checked yet, not "inactive"

    databases = get_databases()
    async with databases.app_session_factory() as session:
        row = await session.get(Device, device["id"])
        row.status = HealthStatus.DOWN
        row.last_seen_at = utcnow()
        await session.commit()
    just_down = (await client.get(f"/api/devices/{device['id']}")).json()
    assert just_down["inactive"] is False  # down, but only just - a blip, not yet "inactive"

    async with databases.app_session_factory() as session:
        row = await session.get(Device, device["id"])
        row.last_seen_at = utcnow() - INACTIVE_AFTER - datetime.timedelta(seconds=1)
        await session.commit()
    stale = (await client.get(f"/api/devices/{device['id']}")).json()
    assert stale["inactive"] is True

    async with databases.app_session_factory() as session:
        row = await session.get(Device, device["id"])
        row.status = HealthStatus.UP
        await session.commit()
    recovered = (await client.get(f"/api/devices/{device['id']}")).json()
    assert recovered["inactive"] is False  # back up clears the flag immediately
