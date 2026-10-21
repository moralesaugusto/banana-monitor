import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_list_network(client: AsyncClient) -> None:
    response = await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.1.0/24"})
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "LAN"
    assert created["site_id"] == 1

    response = await client.get("/api/networks")
    assert response.status_code == 200
    assert [n["name"] for n in response.json()] == ["LAN"]


@pytest.mark.asyncio
async def test_get_update_delete_network(client: AsyncClient) -> None:
    created = (
        await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.1.0/24"})
    ).json()
    network_id = created["id"]

    response = await client.get(f"/api/networks/{network_id}")
    assert response.status_code == 200

    response = await client.patch(f"/api/networks/{network_id}", json={"description": "main LAN"})
    assert response.status_code == 200
    assert response.json()["description"] == "main LAN"

    response = await client.delete(f"/api/networks/{network_id}")
    assert response.status_code == 204

    response = await client.get(f"/api/networks/{network_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_missing_network_404(client: AsyncClient) -> None:
    response = await client.get("/api/networks/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_add_list_remove_network_credential_binding(client: AsyncClient) -> None:
    network = (await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.1.0/24"})).json()
    credential = (
        await client.post(
            "/api/credentials",
            json={
                "label": "homelab-ssh",
                "credential_type": "ssh_key",
                "secret": {"username": "x", "private_key": "y"},
            },
        )
    ).json()

    response = await client.post(
        f"/api/networks/{network['id']}/credentials",
        json={"credential_id": credential["id"], "priority": 0},
    )
    assert response.status_code == 201
    binding = response.json()
    assert binding["credential_id"] == credential["id"]

    response = await client.get(f"/api/networks/{network['id']}/credentials")
    assert response.status_code == 200
    assert len(response.json()) == 1

    response = await client.delete(f"/api/networks/{network['id']}/credentials/{binding['id']}")
    assert response.status_code == 204
    assert (await client.get(f"/api/networks/{network['id']}/credentials")).json() == []


@pytest.mark.asyncio
async def test_add_network_credential_unknown_credential_400(client: AsyncClient) -> None:
    network = (await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.1.0/24"})).json()
    response = await client.post(
        f"/api/networks/{network['id']}/credentials", json={"credential_id": 999, "priority": 0}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_network_map_small_network_returns_per_address_grid(client: AsyncClient) -> None:
    network = (await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.50.0/30"})).json()

    from app.db.session import get_databases
    from app.discovery.service import DiscoveryService

    discovery_service = DiscoveryService(get_databases())
    await discovery_service.record_device_observation(
        network_id=network["id"], ip="192.168.50.1", mac=None, hostname="gw",
        open_ports=[], via="network_scan",
    )

    response = await client.get(f"/api/networks/{network['id']}/map")
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is False
    assert body["total_addresses"] == 2  # a /30 has 2 usable host addresses
    by_ip = {a["ip"]: a for a in body["addresses"]}
    assert by_ip["192.168.50.1"]["display_name"] == "gw"
    assert by_ip["192.168.50.1"]["managed"] is False
    other_ip = next(ip for ip in by_ip if ip != "192.168.50.1")
    assert by_ip[other_ip]["status"] is None  # free


@pytest.mark.asyncio
async def test_network_map_large_network_returns_summary(client: AsyncClient) -> None:
    network = (await client.post("/api/networks", json={"name": "Big", "cidr": "10.0.0.0/16"})).json()

    response = await client.get(f"/api/networks/{network['id']}/map")
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert body["addresses"] == []
    assert body["summary"] is not None


@pytest.mark.asyncio
async def test_network_map_missing_network_404(client: AsyncClient) -> None:
    response = await client.get("/api/networks/999/map")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_scan_status_defaults_to_idle(client: AsyncClient) -> None:
    network = (await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.60.0/30"})).json()

    response = await client.get(f"/api/networks/{network['id']}/scan-status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "idle"
    assert body["total_hosts"] == 0
    assert body["scanned_hosts"] == 0


@pytest.mark.asyncio
async def test_scan_status_advances_then_finishes(client: AsyncClient) -> None:
    network = (await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.61.0/30"})).json()

    from app.discovery.scan_status import get_scan_status_registry

    registry = get_scan_status_registry()
    registry.start(network["id"], total_hosts=2)
    mid_response = await client.get(f"/api/networks/{network['id']}/scan-status")
    assert mid_response.json()["status"] == "scanning"
    assert mid_response.json()["total_hosts"] == 2

    registry.advance(network["id"])
    registry.finish(network["id"])
    done_response = await client.get(f"/api/networks/{network['id']}/scan-status")
    body = done_response.json()
    assert body["status"] == "idle"
    assert body["scanned_hosts"] == 1
    assert body["finished_at"] is not None


@pytest.mark.asyncio
async def test_scan_status_missing_network_404(client: AsyncClient) -> None:
    response = await client.get("/api/networks/999/scan-status")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_network_keeps_its_devices_and_candidates(client: AsyncClient) -> None:
    from sqlalchemy import select

    from app.db.session import get_databases
    from app.domain.enums import CandidateStatus, CandidateType
    from app.domain.models import DiscoveredCandidate, utcnow

    network_id = (
        await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.1.0/24"})
    ).json()["id"]
    device_id = (
        await client.post(
            "/api/devices",
            json={"display_name": "pve1", "device_type": "proxmox_node", "network_id": network_id},
        )
    ).json()["id"]
    async with get_databases().app_session_factory() as session:
        now = utcnow()
        session.add(
            DiscoveredCandidate(
                candidate_type=CandidateType.DEVICE,
                fingerprint="seen-on-lan",
                discovered_via="network_scan",
                network_id=network_id,
                first_seen_at=now,
                last_seen_at=now,
                status=CandidateStatus.PENDING,
            )
        )
        await session.commit()

    assert (await client.delete(f"/api/networks/{network_id}")).status_code == 204

    assert (await client.get(f"/api/networks/{network_id}")).status_code == 404
    assert (await client.get(f"/api/devices/{device_id}")).json()["network_id"] is None
    async with get_databases().app_session_factory() as session:
        candidate = (await session.execute(select(DiscoveredCandidate))).scalar_one()
        assert candidate.network_id is None
