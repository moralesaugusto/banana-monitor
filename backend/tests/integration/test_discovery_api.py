import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.discovery.service import DiscoveryService


@pytest.mark.asyncio
async def test_device_candidate_auto_provisions_device(client: AsyncClient) -> None:
    """Device candidates no longer wait in the review queue - see
    docs/decisions.md "Auto-populate discovered devices"."""
    discovery_service = DiscoveryService(get_databases())
    await discovery_service.record_device_observation(
        network_id=None, ip="192.168.1.20", mac="aa:bb:cc:00:11:22", hostname="host2",
        open_ports=[22], via="network_scan",
    )

    response = await client.get("/api/discovery/candidates")
    assert response.status_code == 200
    assert response.json() == []  # nothing pending - it was auto-accepted

    accepted = (await client.get("/api/discovery/candidates?status=accepted")).json()
    assert len(accepted) == 1
    device_id = accepted[0]["resulting_device_id"]

    device_response = await client.get(f"/api/devices/{device_id}")
    assert device_response.status_code == 200
    assert device_response.json()["display_name"] == "host2"
    assert device_response.json()["managed"] is False


@pytest.mark.asyncio
async def test_ignore_candidate(client: AsyncClient) -> None:
    """Device candidates auto-accept now (see above), so this exercises
    ignore() against a still-pending service candidate instead."""
    discovery_service = DiscoveryService(get_databases())
    await discovery_service.record_service_observation(
        network_id=None, ip="192.168.1.21", port=443, protocol="https", attributes={}, via="network_scan"
    )
    candidate_id = (await client.get("/api/discovery/candidates")).json()[0]["id"]

    response = await client.post(f"/api/discovery/candidates/{candidate_id}/ignore")
    assert response.status_code == 204

    assert (await client.get("/api/discovery/candidates")).json() == []


@pytest.mark.asyncio
async def test_accept_service_registers_with_live_scheduler(client: AsyncClient) -> None:
    """Regression test: accepting a discovered service must start it polling
    immediately, not just after the next app restart."""
    discovery_service = DiscoveryService(get_databases())
    await discovery_service.record_service_observation(
        network_id=None, ip="192.168.1.30", port=443, protocol="https", attributes={}, via="network_scan"
    )
    candidate_id = (await client.get("/api/discovery/candidates")).json()[0]["id"]

    from app.scheduler.supervisor import get_supervisor

    supervisor = get_supervisor()
    supervisor._running = True
    try:
        response = await client.post(
            f"/api/discovery/candidates/{candidate_id}/accept-service",
            json={"service_type": "https", "config": {"url": "https://192.168.1.30"}},
        )
        assert response.status_code == 201
        service_id = response.json()["id"]
        assert service_id in supervisor._service_tasks
    finally:
        await supervisor.stop()


@pytest.mark.asyncio
async def test_accept_unknown_candidate_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/discovery/candidates/999/accept-device", json={"device_type": "linux"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_candidate_type_filter_excludes_leftover_pending_device_candidates(
    client: AsyncClient,
) -> None:
    """A device candidate created before auto-populate shipped (or any other
    way a DEVICE candidate ends up still `pending`) must not show up in the
    `candidate_type=service` listing the Discovery page uses - otherwise the
    frontend renders it as a service row and "Accept" 404s against
    accept-service, which only ever matches SERVICE candidates."""
    from app.domain.enums import CandidateStatus, CandidateType
    from app.domain.models import DiscoveredCandidate, utcnow

    databases = get_databases()
    async with databases.app_session_factory() as session:
        now = utcnow()
        session.add(
            DiscoveredCandidate(
                candidate_type=CandidateType.DEVICE,
                fingerprint="leftover-device",
                discovered_via="network_scan",
                network_id=None,
                raw_attributes={"ip": "192.168.1.40"},
                first_seen_at=now,
                last_seen_at=now,
                times_seen=1,
                status=CandidateStatus.PENDING,
            )
        )
        await session.commit()

    all_pending = (await client.get("/api/discovery/candidates")).json()
    assert len(all_pending) == 1

    service_only = (await client.get("/api/discovery/candidates?candidate_type=service")).json()
    assert service_only == []


@pytest.mark.asyncio
async def test_trigger_network_scan_returns_202(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_scan(databases: object, network_id: int) -> None:
        return None

    # The real scanner is covered by dedicated network_scanner/technique tests;
    # here we only care that the endpoint schedules *something* and returns
    # immediately, without leaving a real background scan running past the test.
    monkeypatch.setattr("app.api.routes.networks.scan_network", fake_scan)

    network = (
        await client.post("/api/networks", json={"name": "LAN", "cidr": "127.0.0.1/32"})
    ).json()

    response = await client.post(f"/api/networks/{network['id']}/scan")
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_trigger_scan_missing_network_404(client: AsyncClient) -> None:
    response = await client.post("/api/networks/999/scan")
    assert response.status_code == 404
