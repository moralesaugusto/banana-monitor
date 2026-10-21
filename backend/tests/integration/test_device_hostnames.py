import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_databases
from app.discovery import network_scanner
from app.discovery.techniques import arp, device_names, dns_probe, http_probe, icmp, tcp_ports, tls_probe
from app.domain.models import Device


async def _ping(ip: str) -> bool:
    return True


async def _arp() -> dict[str, str]:
    return {}


async def _ports(host: str, ports: list[int] | None = None, timeout: float = 0.5) -> list[int]:
    return [8443] if host.endswith(".1") else []


async def _no_http(host: str, port: int, timeout: float = 3.0) -> None:
    return None


def _answers(monkeypatch: pytest.MonkeyPatch, *, dns=None, mdns=None, netbios=None, cn=None) -> list:  # noqa: ANN001
    asked: list = []

    async def reverse_dns(ip: str, timeout: float = 2.0, server: str | None = None) -> str | None:
        asked.append(server)
        return dns

    async def mdns_name(ip: str, timeout: float = 1.0) -> str | None:
        return mdns

    async def netbios_name(ip: str, timeout: float = 1.0) -> str | None:
        return netbios

    async def probe_tls(host: str, port: int, timeout: float = 3.0) -> dict[str, str] | None:
        return {"common_name": cn, "not_after": "2030-01-01T00:00:00+00:00"} if cn else None

    for target, fake in (
        (icmp, ("ping_host", _ping)),
        (arp, ("get_arp_table", _arp)),
        (tcp_ports, ("scan_ports", _ports)),
        (http_probe, ("probe_http", _no_http)),
        (dns_probe, ("reverse_dns", reverse_dns)),
        (device_names, ("mdns_name", mdns_name)),
        (device_names, ("netbios_name", netbios_name)),
        (tls_probe, ("probe_tls", probe_tls)),
    ):
        monkeypatch.setattr(target, *fake)
    return asked


async def _scan(client: AsyncClient, cidr: str) -> Device:
    network = (await client.post("/api/networks", json={"name": cidr, "cidr": cidr})).json()
    await network_scanner.scan_network(get_databases(), network["id"])
    async with get_databases().app_session_factory() as session:
        return (await session.scalars(select(Device).where(Device.primary_ip.like("%.1")))).one()


@pytest.mark.asyncio
async def test_a_scan_names_the_device_from_the_best_answer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, mdns="macbook.local", netbios="MACBOOK", cn="device.example")
    device = await _scan(client, "10.98.1.0/30")
    # mDNS beats NetBIOS, which beats the certificate name.
    assert (device.hostname, device.hostname_source, device.display_name) == (
        "macbook.local",
        "mdns",
        "macbook.local",
    )


@pytest.mark.asyncio
async def test_a_dns_name_beats_the_devices_own_answers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, dns="nas.lan", mdns="nas.local", netbios="NAS")
    device = await _scan(client, "10.98.2.0/30")
    assert (device.hostname, device.hostname_source) == ("nas.lan", "dns")


@pytest.mark.asyncio
async def test_the_certificate_name_is_used_when_nothing_else_answers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, cn="omada.home")
    device = await _scan(client, "10.98.3.0/30")
    assert (device.hostname, device.hostname_source) == ("omada.home", "tls")


@pytest.mark.asyncio
async def test_a_certificate_name_that_is_not_a_host_name_is_ignored(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, cn="TP-Link Omada Controller")
    device = await _scan(client, "10.98.4.0/30")
    assert device.hostname is None and device.display_name == device.primary_ip


@pytest.mark.asyncio
async def test_a_later_scan_improves_the_name_but_never_worsens_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, netbios="OLD-NAME")
    device = await _scan(client, "10.98.5.0/30")
    assert device.hostname_source == "netbios"

    _answers(monkeypatch, dns="router-assigned.lan")
    network_id = (await client.get("/api/networks")).json()[0]["id"]
    await network_scanner.scan_network(get_databases(), network_id)
    async with get_databases().app_session_factory() as session:
        device = (await session.scalars(select(Device).where(Device.primary_ip.like("%.1")))).one()
    assert (device.hostname, device.hostname_source) == ("router-assigned.lan", "dns")

    _answers(monkeypatch, cn="later.example")
    await network_scanner.scan_network(get_databases(), network_id)
    async with get_databases().app_session_factory() as session:
        device = (await session.scalars(select(Device).where(Device.primary_ip.like("%.1")))).one()
    assert device.hostname == "router-assigned.lan"


@pytest.mark.asyncio
async def test_a_configured_dns_server_is_the_one_asked(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _answers(monkeypatch, dns="x.lan")
    assert (
        await client.put("/api/system/discovery-settings", json={"dns_server": "192.168.1.3"})
    ).status_code == 200
    assert (
        await client.put("/api/system/discovery-settings", json={"dns_server": "bad value;"})
    ).status_code == 422
    await _scan(client, "10.98.6.0/30")
    assert "192.168.1.3" in asked


@pytest.mark.asyncio
async def test_a_hostname_typed_by_a_person_is_never_overwritten(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"display_name": "Mine", "device_type": "other", "primary_ip": "10.98.7.1", "hostname": "my-box"}
    device = (await client.post("/api/devices", json=body)).json()
    _answers(monkeypatch, dns="from-dns.lan")
    network = (await client.post("/api/networks", json={"name": "n", "cidr": "10.98.7.0/30"})).json()
    await network_scanner.scan_network(get_databases(), network["id"])
    refreshed = (await client.get(f"/api/devices/{device['id']}")).json()
    assert refreshed["hostname"] == "my-box" and refreshed["display_name"] == "Mine"


@pytest.mark.asyncio
async def test_a_certificate_name_shared_by_two_devices_names_neither(client: AsyncClient) -> None:
    from app.discovery.service import DiscoveryService

    service = DiscoveryService(get_databases())
    ids = []
    for ip in ("10.97.0.1", "10.97.0.2"):
        body = {"display_name": ip, "device_type": "other", "primary_ip": ip}
        ids.append((await client.post("/api/devices", json=body)).json()["id"])

    async def saw_certificate(ip: str) -> None:  # what a scan records for a TLS port
        tls = {"tls": {"common_name": "vendor-default.example"}}
        await service.record_service_observation(
            network_id=None, ip=ip, port=443, protocol="https", attributes=tls, via="network_scan"
        )

    # The first device is scanned while nobody else shows that certificate: it takes the name.
    await saw_certificate("10.97.0.1")
    await service.set_hostname(ids[0], "vendor-default.example", "tls")
    first = (await client.get(f"/api/devices/{ids[0]}")).json()
    assert first["hostname"] == "vendor-default.example"

    # The second device shows the same certificate: neither gets the name, and the first one loses it.
    await saw_certificate("10.97.0.2")
    await service.set_hostname(ids[1], "vendor-default.example", "tls")
    first, second = [(await client.get(f"/api/devices/{i}")).json() for i in ids]
    assert first["hostname"] is None and first["display_name"] == "10.97.0.1"
    assert second["hostname"] is None

    # It stays that way on later scans, and a better source is not held back.
    await service.set_hostname(ids[0], "vendor-default.example", "tls")
    assert (await client.get(f"/api/devices/{ids[0]}")).json()["hostname"] is None
    await service.set_hostname(ids[1], "second.lan", "dns")
    assert (await client.get(f"/api/devices/{ids[1]}")).json()["hostname"] == "second.lan"
