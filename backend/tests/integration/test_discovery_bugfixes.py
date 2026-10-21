"""Regression tests for the five problems in docs/bugs+2026-10-08-183232.md."""

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app import background
from app.db.session import get_databases
from app.discovery import network_scanner
from app.discovery.service import DiscoveryService
from app.discovery.techniques import icmp
from app.domain.enums import IntegrationStatus
from app.domain.models import (
    Device,
    DeviceAddress,
    DiscoveredCandidate,
    Integration,
    Service,
)

# --- 1. accepting a service candidate twice -------------------------------------------------------


async def _service_candidate(client: AsyncClient) -> int:
    await DiscoveryService(get_databases()).record_service_observation(
        network_id=None,
        ip="10.0.0.5",
        port=8080,
        protocol="http",
        attributes={"ip": "10.0.0.5", "port": 8080},
        via="test",
    )
    return (await client.get("/api/discovery/candidates?candidate_type=service")).json()[0]["id"]


ACCEPT = {"service_type": "tcp", "config": {"host": "10.0.0.5", "port": 8080}}


async def test_a_service_candidate_can_only_be_accepted_once(client: AsyncClient) -> None:
    candidate = await _service_candidate(client)
    first = await client.post(f"/api/discovery/candidates/{candidate}/accept-service", json=ACCEPT)
    second = await client.post(f"/api/discovery/candidates/{candidate}/accept-service", json=ACCEPT)
    assert (first.status_code, second.status_code) == (201, 409)
    async with get_databases().app_session_factory() as session:
        assert len((await session.scalars(select(Service))).all()) == 1


async def test_an_ignored_candidate_cannot_be_accepted(client: AsyncClient) -> None:
    candidate = await _service_candidate(client)
    assert (await client.post(f"/api/discovery/candidates/{candidate}/ignore")).status_code == 204
    refused = await client.post(f"/api/discovery/candidates/{candidate}/accept-service", json=ACCEPT)
    assert refused.status_code == 409


# --- 2. one failing host or network must not abort the scan --------------------------------------


async def test_a_failing_host_does_not_stop_the_scan(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, cidr in (("a", "10.9.0.0/30"), ("b", "10.9.1.0/30")):
        await client.post("/api/networks", json={"name": name, "cidr": cidr})
    attempted: list[str] = []

    async def flaky_ping(host: str, *args: object, **kwargs: object) -> bool:
        attempted.append(host)
        if host == "10.9.0.1":
            raise RuntimeError("boom")
        return False

    async def no_ports(host: str, *args: object, **kwargs: object) -> list[int]:
        return []

    async def no_arp() -> dict[str, str]:
        return {}

    monkeypatch.setattr(network_scanner.icmp, "ping_host", flaky_ping)
    monkeypatch.setattr(network_scanner.tcp_ports, "scan_ports", no_ports)
    monkeypatch.setattr(network_scanner.arp, "get_arp_table", no_arp)

    await network_scanner.run_discovery_for_all_networks(get_databases())  # must not raise

    assert sorted(attempted) == ["10.9.0.1", "10.9.0.2", "10.9.1.1", "10.9.1.2"]  # both networks, all hosts
    networks = (await client.get("/api/networks")).json()
    first = (await client.get(f"/api/networks/{networks[0]['id']}/scan-status")).json()
    assert first["failed_hosts"] == 1 and first["status"] == "idle" and first["scanned_hosts"] == 2


async def test_a_failing_network_does_not_stop_the_others(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, cidr in (("a", "10.9.0.0/30"), ("b", "10.9.1.0/30")):
        await client.post("/api/networks", json={"name": name, "cidr": cidr})
    scanned: list[int] = []
    real = network_scanner.scan_network

    async def scan(databases: object, network_id: int) -> None:
        scanned.append(network_id)
        if len(scanned) == 1:
            raise RuntimeError("first network exploded")
        await real(databases, network_id)  # type: ignore[arg-type]

    monkeypatch.setattr(network_scanner, "scan_network", scan)
    await network_scanner.run_discovery_for_all_networks(get_databases())
    assert len(scanned) == 2


async def test_a_system_without_ping_reports_hosts_as_not_answering() -> None:
    async def missing(args: list[str]) -> tuple[int, str, str]:
        raise FileNotFoundError("ping")

    assert await icmp.ping_host("10.0.0.1", runner=missing) is False


# --- 3. background tasks are kept alive, logged and cancelled at shutdown ------------------------


async def test_background_tasks_are_tracked_and_cancelled(caplog: pytest.LogCaptureFixture) -> None:
    ran = asyncio.Event()

    async def work() -> None:
        ran.set()
        await asyncio.sleep(30)

    task = background.spawn(work(), "demo")
    await asyncio.wait_for(ran.wait(), 1)
    assert task in background._tasks  # a strong reference is held, so it cannot be garbage-collected
    await background.cancel_all()
    assert task.cancelled() and not background._tasks


async def test_a_failing_background_task_is_logged_not_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(background.logger, "error", lambda event, **kw: logged.append((event, kw)))

    async def fail() -> None:
        raise ValueError("kaput")

    task = background.spawn(fail(), "failing-demo")
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert not background._tasks
    assert logged and logged[0][0] == "background_task_failed" and logged[0][1]["task"] == "failing-demo"


# --- 4. a device seen without, then with, a MAC is one device -------------------------------------


async def _devices_at(ip: str) -> list[Device]:
    async with get_databases().app_session_factory() as session:
        return list((await session.scalars(select(Device).where(Device.primary_ip == ip))).all())


async def test_a_mac_learned_later_does_not_create_a_second_device(client: AsyncClient) -> None:
    svc = DiscoveryService(get_databases())
    seen = {"network_id": None, "ip": "10.0.0.7", "hostname": None, "open_ports": [22], "via": "t"}
    first = await svc.record_device_observation(mac=None, **seen)
    second = await svc.record_device_observation(mac="aa:bb:cc:dd:ee:ff", **seen)
    third = await svc.record_device_observation(mac=None, **seen)  # ARP missed it this time
    fourth = await svc.record_device_observation(mac="aa:bb:cc:dd:ee:ff", **seen)

    assert first == second == third == fourth
    assert len(await _devices_at("10.0.0.7")) == 1
    async with get_databases().app_session_factory() as session:
        address = await session.scalar(select(DeviceAddress).where(DeviceAddress.ip_address == "10.0.0.7"))
        candidate = await session.scalar(select(DiscoveredCandidate))
    assert address.mac_address == "aa:bb:cc:dd:ee:ff"  # the device learned its MAC
    assert (
        candidate.fingerprint == "aa:bb:cc:dd:ee:ff"
        and candidate.raw_attributes["mac"] == "aa:bb:cc:dd:ee:ff"
    )


async def test_a_different_mac_on_the_same_ip_is_a_different_device(client: AsyncClient) -> None:
    svc = DiscoveryService(get_databases())
    seen = {"network_id": None, "ip": "10.0.0.8", "hostname": None, "open_ports": [], "via": "t"}
    one = await svc.record_device_observation(mac="aa:aa:aa:aa:aa:01", **seen)
    two = await svc.record_device_observation(
        mac="aa:aa:aa:aa:aa:02", **seen
    )  # DHCP handed the IP to other hardware
    assert one != two


async def test_existing_duplicates_are_merged_at_startup(client: AsyncClient) -> None:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        # How the old matching left things: one device found without a MAC, one with.
        a = Device(site_id=1, display_name="a", primary_ip="10.0.0.9", device_type="other", managed=False)
        b = Device(site_id=1, display_name="b", primary_ip="10.0.0.9", device_type="other", managed=False)
        session.add_all([a, b])
        await session.flush()
        session.add_all(
            [
                DeviceAddress(device_id=a.id, ip_address="10.0.0.9", is_primary=True),
                DeviceAddress(
                    device_id=b.id, ip_address="10.0.0.9", mac_address="aa:bb:cc:00:00:09", is_primary=True
                ),
                Service(device_id=b.id, name="web", service_type="tcp", config={}, port=80, managed=False),
                # a conflicting pair that must be left alone: two different MACs on one IP
                Device(
                    site_id=1, display_name="c", primary_ip="10.0.0.10", device_type="other", managed=False
                ),
                Device(
                    site_id=1, display_name="d", primary_ip="10.0.0.10", device_type="other", managed=False
                ),
            ]
        )
        await session.flush()
        c, d = (await session.scalars(select(Device).where(Device.primary_ip == "10.0.0.10"))).all()
        session.add_all(
            [
                DeviceAddress(
                    device_id=c.id, ip_address="10.0.0.10", mac_address="11:11:11:11:11:11", is_primary=True
                ),
                DeviceAddress(
                    device_id=d.id, ip_address="10.0.0.10", mac_address="22:22:22:22:22:22", is_primary=True
                ),
            ]
        )
        await session.commit()
        keeper_id = a.id

    assert await DiscoveryService(databases).merge_duplicate_devices() == 1

    merged = await _devices_at("10.0.0.9")
    assert [d.id for d in merged] == [keeper_id]
    async with databases.app_session_factory() as session:
        address = await session.scalar(select(DeviceAddress).where(DeviceAddress.device_id == keeper_id))
        service = await session.scalar(select(Service))
    assert address.mac_address == "aa:bb:cc:00:00:09" and service.device_id == keeper_id
    assert len(await _devices_at("10.0.0.10")) == 2  # conflicting MACs: not merged


# --- 5. an integration whose credential is gone shows an error -------------------------------------


async def test_missing_credential_marks_the_integration_as_failing(client: AsyncClient) -> None:
    from app.scheduler.supervisor import get_supervisor

    databases = get_databases()
    supervisor = get_supervisor()
    supervisor._running = True
    async with databases.app_session_factory() as session:
        integration = Integration(
            integration_type="generic_ssh",
            name="nas",
            config={"host": "10.0.0.9"},
            credential_id=999,
            enabled=True,
        )
        session.add(integration)
        await session.commit()
        await session.refresh(integration)

    await supervisor.add_integration(integration)

    async with databases.app_session_factory() as session:
        row = await session.get(Integration, integration.id)
    assert row.status == IntegrationStatus.ERROR and "Credential unavailable" in row.last_error
    assert integration.id not in supervisor._integration_tasks


async def test_a_credential_in_use_cannot_be_deleted(client: AsyncClient) -> None:
    credential = (
        await client.post(
            "/api/credentials",
            json={"label": "k", "credential_type": "api_token", "secret": {"token": "x"}},
        )
    ).json()
    async with get_databases().app_session_factory() as session:
        session.add(
            Integration(integration_type="proxmox", name="pve", config={}, credential_id=credential["id"])
        )
        await session.commit()

    refused = await client.delete(f"/api/credentials/{credential['id']}")
    assert refused.status_code == 409 and "integration pve" in refused.json()["detail"]

    unused = (
        await client.post(
            "/api/credentials",
            json={"label": "free", "credential_type": "api_token", "secret": {"token": "y"}},
        )
    ).json()
    assert (await client.delete(f"/api/credentials/{unused['id']}")).status_code == 204
