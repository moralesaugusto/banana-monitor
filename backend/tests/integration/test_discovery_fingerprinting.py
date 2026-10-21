import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.discovery import network_scanner
from app.discovery.scan_status import get_scan_status_registry
from app.discovery.service import DiscoveryService
from app.discovery.techniques import arp, dns_probe, http_probe, icmp, tcp_ports
from app.domain.enums import CandidateType


@pytest.mark.asyncio
async def test_scan_attaches_suggested_integration_type_to_service_candidate(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end wiring check: network_scanner's HTTP-probe-based fingerprint
    hint must land in a discovered service candidate's raw_attributes, since
    that's the only place a future frontend pass can read it from (no schema
    change per the discovery review flow's existing contract)."""
    network = (
        await client.post("/api/networks", json={"name": "LAN", "cidr": "10.99.99.0/30"})
    ).json()

    monkeypatch.setattr(icmp, "ping_host", _fake_ping)
    monkeypatch.setattr(arp, "get_arp_table", _fake_arp_table)
    monkeypatch.setattr(dns_probe, "reverse_dns", _fake_reverse_dns)
    monkeypatch.setattr(tcp_ports, "scan_ports", _fake_scan_ports)
    monkeypatch.setattr(http_probe, "probe_http", _fake_probe_http)

    await network_scanner.scan_network(get_databases(), network["id"])

    discovery_service = DiscoveryService(get_databases())
    candidates = await discovery_service.list_candidates(status=None)
    service_candidates = [c for c in candidates if c.candidate_type == CandidateType.SERVICE]
    assert len(service_candidates) == 1
    assert service_candidates[0].raw_attributes["suggested_integration_type"] == "adguard_home"
    assert service_candidates[0].raw_attributes["port"] == 3000

    status = get_scan_status_registry().get(network["id"])
    assert status.status == "idle"  # finished
    assert status.scanned_hosts == status.total_hosts > 0


@pytest.mark.asyncio
async def test_scan_attaches_banner_for_non_http_open_port(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-HTTP open port (no http_info) gets a plain TCP banner read
    instead - see docs/discovery.md, the nmap-free alternative."""
    from app.discovery.techniques import banner_grab

    network = (
        await client.post("/api/networks", json={"name": "LAN3", "cidr": "10.99.97.0/30"})
    ).json()

    monkeypatch.setattr(icmp, "ping_host", _fake_ping)
    monkeypatch.setattr(arp, "get_arp_table", _fake_arp_table)
    monkeypatch.setattr(dns_probe, "reverse_dns", _fake_reverse_dns)
    monkeypatch.setattr(tcp_ports, "scan_ports", _fake_scan_ports_ssh_only)
    monkeypatch.setattr(http_probe, "probe_http", _fake_probe_http_none)
    monkeypatch.setattr(
        banner_grab, "grab_banner", _fake_grab_banner_ssh
    )

    await network_scanner.scan_network(get_databases(), network["id"])

    discovery_service = DiscoveryService(get_databases())
    candidates = await discovery_service.list_candidates(status=None)
    service_candidates = [c for c in candidates if c.candidate_type == CandidateType.SERVICE]
    assert len(service_candidates) == 1
    assert service_candidates[0].raw_attributes["banner"] == "SSH-2.0-OpenSSH_9.6"


@pytest.mark.asyncio
async def test_scan_leaves_suggestion_out_when_no_confident_guess(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    network = (
        await client.post("/api/networks", json={"name": "LAN2", "cidr": "10.99.98.0/30"})
    ).json()

    monkeypatch.setattr(icmp, "ping_host", _fake_ping)
    monkeypatch.setattr(arp, "get_arp_table", _fake_arp_table)
    monkeypatch.setattr(dns_probe, "reverse_dns", _fake_reverse_dns)
    monkeypatch.setattr(tcp_ports, "scan_ports", _fake_scan_ports_unrecognized_port)
    monkeypatch.setattr(http_probe, "probe_http", _fake_probe_http_none)

    await network_scanner.scan_network(get_databases(), network["id"])

    discovery_service = DiscoveryService(get_databases())
    candidates = await discovery_service.list_candidates(status=None)
    service_candidates = [c for c in candidates if c.candidate_type == CandidateType.SERVICE]
    assert len(service_candidates) == 1
    assert "suggested_integration_type" not in service_candidates[0].raw_attributes


@pytest.mark.asyncio
async def test_scan_suggests_generic_ssh_for_port_22_regardless_of_os(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Port 22 means SSH is listening, whatever OS is behind it - the suggestion must not depend on an
    OS guess (there isn't one here at all: nmap OS detection is off by default)."""
    network = (
        await client.post("/api/networks", json={"name": "LAN4", "cidr": "10.99.96.0/30"})
    ).json()

    monkeypatch.setattr(icmp, "ping_host", _fake_ping)
    monkeypatch.setattr(arp, "get_arp_table", _fake_arp_table)
    monkeypatch.setattr(dns_probe, "reverse_dns", _fake_reverse_dns)
    monkeypatch.setattr(tcp_ports, "scan_ports", _fake_scan_ports_ssh_only)
    monkeypatch.setattr(http_probe, "probe_http", _fake_probe_http_none)

    await network_scanner.scan_network(get_databases(), network["id"])

    discovery_service = DiscoveryService(get_databases())
    candidates = await discovery_service.list_candidates(status=None)
    service_candidates = [c for c in candidates if c.candidate_type == CandidateType.SERVICE]
    assert len(service_candidates) == 1
    assert service_candidates[0].raw_attributes["suggested_integration_type"] == "generic_ssh"


async def _fake_ping(host: str) -> bool:
    return False


async def _fake_arp_table() -> dict[str, str]:
    return {}


async def _fake_reverse_dns(ip: str, timeout: float = 2.0, server: str | None = None) -> str | None:
    return None


async def _fake_scan_ports(host: str, ports: list[int] | None = None, timeout: float = 0.5) -> list[int]:
    return [3000] if host.endswith(".1") else []


async def _fake_probe_http(host: str, port: int, timeout: float = 3.0) -> dict[str, str] | None:
    if port == 3000:
        return {"status_code": "200", "server": "", "title": "AdGuard Home"}
    return None


async def _fake_scan_ports_ssh_only(
    host: str, ports: list[int] | None = None, timeout: float = 0.5
) -> list[int]:
    return [22] if host.endswith(".1") else []


async def _fake_scan_ports_unrecognized_port(
    host: str, ports: list[int] | None = None, timeout: float = 0.5
) -> list[int]:
    return [9999] if host.endswith(".1") else []


async def _fake_probe_http_none(host: str, port: int, timeout: float = 3.0) -> dict[str, str] | None:
    return None


async def _fake_grab_banner_ssh(host: str, port: int, timeout: float = 1.5) -> str | None:
    return "SSH-2.0-OpenSSH_9.6" if port == 22 else None
