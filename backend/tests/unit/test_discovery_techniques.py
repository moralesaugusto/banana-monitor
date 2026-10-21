import asyncio

import pytest

from app.discovery.techniques import arp, fingerprint, icmp, tcp_ports


async def _fake_runner_success(args: list[str]) -> tuple[int, str, str]:
    return 0, "", ""


async def _fake_runner_failure(args: list[str]) -> tuple[int, str, str]:
    return 1, "", "unreachable"


@pytest.mark.asyncio
async def test_ping_host_success() -> None:
    assert await icmp.ping_host("192.168.1.1", runner=_fake_runner_success) is True


@pytest.mark.asyncio
async def test_ping_host_failure() -> None:
    assert await icmp.ping_host("192.168.1.1", runner=_fake_runner_failure) is False


IP_NEIGH_OUTPUT = (
    "192.168.1.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n"
    "192.168.1.2 dev eth0  FAILED\n"
    "192.168.1.3 dev eth0 lladdr 11:22:33:44:55:66 STALE\n"
)


@pytest.mark.asyncio
async def test_get_arp_table_parses_lladdr_entries() -> None:
    async def runner(args: list[str]) -> tuple[int, str, str]:
        return 0, IP_NEIGH_OUTPUT, ""

    table = await arp.get_arp_table(runner=runner)

    assert table == {
        "192.168.1.1": "aa:bb:cc:dd:ee:ff",
        "192.168.1.3": "11:22:33:44:55:66",
    }


@pytest.mark.asyncio
async def test_get_arp_table_returns_empty_on_command_failure() -> None:
    async def runner(args: list[str]) -> tuple[int, str, str]:
        return 1, "", "error"

    assert await arp.get_arp_table(runner=runner) == {}


@pytest.mark.asyncio
async def test_scan_ports_finds_open_and_skips_closed() -> None:
    # Python 3.12's Server.wait_closed() waits for every accepted connection to be closed,
    # so the handler must close its side or the test hangs on teardown.
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    open_port = server.sockets[0].getsockname()[1]

    try:
        found = await tcp_ports.scan_ports("127.0.0.1", ports=[open_port, 1], timeout=0.3)
        assert found == [open_port]
    finally:
        server.close()
        await server.wait_closed()


def test_common_ports_include_new_service_signals() -> None:
    for port in (53, 3000, 8043, 8843, 8581):
        assert port in tcp_ports.COMMON_PORTS


def test_fingerprint_matches_adguard_home_by_title() -> None:
    guess = fingerprint.suggest_integration_type(3000, {"title": "AdGuard Home", "server": ""})
    assert guess == "adguard_home"


def test_fingerprint_matches_homebridge_by_title() -> None:
    guess = fingerprint.suggest_integration_type(8581, {"title": "Homebridge", "server": ""})
    assert guess == "homebridge"


def test_fingerprint_matches_omada_by_title() -> None:
    guess = fingerprint.suggest_integration_type(8043, {"title": "TP-Link Omada Controller", "server": ""})
    assert guess == "omada"


def test_fingerprint_falls_back_to_port_hint_without_http_info() -> None:
    assert fingerprint.suggest_integration_type(3000, None) == "adguard_home"
    assert fingerprint.suggest_integration_type(8581, None) == "homebridge"
    assert fingerprint.suggest_integration_type(8043, None) == "omada"
    assert fingerprint.suggest_integration_type(8843, None) == "omada"


def test_fingerprint_suggests_generic_ssh_for_port_22_regardless_of_os() -> None:
    """Port 22 means SSH is listening, whatever OS is behind it - never gated on a guessed OS,
    matching attempt_ssh_auto_login's own port-only check (network_scanner.py)."""
    assert fingerprint.suggest_integration_type(22, None) == "generic_ssh"
    assert fingerprint.suggest_integration_type(22, {"title": "", "server": ""}) == "generic_ssh"


def test_fingerprint_returns_none_for_unrecognized_port_and_content() -> None:
    assert fingerprint.suggest_integration_type(9999, {"title": "Some Other App", "server": ""}) is None
    assert fingerprint.suggest_integration_type(9999, None) is None


def test_fingerprint_content_signal_overrides_unrelated_port() -> None:
    # A non-standard port serving AdGuard Home's UI (e.g. behind a custom
    # reverse-proxy port) should still be recognized via the page title.
    guess = fingerprint.suggest_integration_type(9090, {"title": "AdGuard Home", "server": ""})
    assert guess == "adguard_home"
