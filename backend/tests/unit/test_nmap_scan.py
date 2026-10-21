import pytest

from app.discovery.techniques import nmap_scan

_SAMPLE_XML = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <ports>
      <port protocol="tcp" portid="22">
        <service name="ssh" product="OpenSSH" version="8.4p1" extrainfo="Debian"/>
      </port>
      <port protocol="tcp" portid="80">
        <service name="http"/>
      </port>
    </ports>
    <os>
      <osmatch name="Linux 5.4 - 5.14" accuracy="93"/>
      <osmatch name="Linux 4.x" accuracy="80"/>
    </os>
  </host>
</nmaprun>
"""


@pytest.fixture(autouse=True)
def _reset_warned_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nmap_scan, "_warned_unavailable", False)


@pytest.mark.asyncio
async def test_scan_host_parses_os_and_service_info() -> None:
    async def fake_runner(args: list[str]) -> tuple[int, str, str]:
        return 0, _SAMPLE_XML, ""

    result = await nmap_scan.scan_host("192.168.1.10", runner=fake_runner)

    assert result is not None
    assert result.os_name == "Linux 5.4 - 5.14"
    assert result.os_accuracy == 93
    assert result.services[22] == {"product": "OpenSSH", "version": "8.4p1", "extrainfo": "Debian"}
    assert 80 not in result.services  # no product/version attributes to report


@pytest.mark.asyncio
async def test_scan_host_returns_none_without_root_privileges() -> None:
    async def fake_runner(args: list[str]) -> tuple[int, str, str]:
        return 1, "", "TCP/IP fingerprinting (for OS scan) requires root privileges.\nQUITTING!\n"

    result = await nmap_scan.scan_host("192.168.1.10", runner=fake_runner)

    assert result is None


@pytest.mark.asyncio
async def test_scan_host_returns_none_when_nmap_not_installed() -> None:
    async def fake_runner(args: list[str]) -> tuple[int, str, str]:
        raise FileNotFoundError("nmap")

    result = await nmap_scan.scan_host("192.168.1.10", runner=fake_runner)

    assert result is None


_SERVICE_XML = """<?xml version="1.0"?>
<nmaprun><host><ports>
  <port protocol="tcp" portid="22"><state state="open"/>
    <service name="ssh" product="OpenSSH" version="9.2"/></port>
  <port protocol="tcp" portid="443"><state state="open"/>
    <service name="http" tunnel="ssl" product="nginx"/></port>
  <port protocol="tcp" portid="23"><state state="closed"/><service name="telnet"/></port>
</ports></host></nmaprun>
"""


def test_build_service_scan_args_is_aggressive_and_unprivileged() -> None:
    args = nmap_scan.build_service_scan_args("10.0.0.5", [443, 22], nmap_scan.NmapTuning())
    assert "-T4" in args and "-sT" in args and "-sV" in args and "-Pn" in args
    assert "--host-timeout=30s" in args
    assert args[args.index("-p") + 1] == "22,443"
    assert "-O" not in args


def test_parse_service_scan_xml_keeps_only_open_ports() -> None:
    parsed = nmap_scan.parse_service_scan_xml(_SERVICE_XML)
    assert set(parsed) == {22, 443}
    assert parsed[22]["product"] == "OpenSSH"
    assert nmap_scan.service_type_for(parsed[443], 443) == "https"
    assert nmap_scan.service_type_for(parsed[22], 22) == "tcp"


@pytest.mark.asyncio
async def test_fingerprint_services_returns_empty_when_nmap_missing() -> None:
    async def missing(args: list[str]) -> tuple[int, str, str]:
        raise FileNotFoundError

    assert await nmap_scan.fingerprint_services("10.0.0.5", [22], nmap_scan.NmapTuning(), missing) == {}
