import asyncio
import struct

import dns.message
import dns.rdatatype
import dns.rrset
import pytest

from app.discovery import hostnames
from app.discovery.techniques import device_names
from app.discovery.techniques.device_names import mdns_name as real_mdns_name
from app.discovery.techniques.device_names import netbios_name as real_netbios_name
from app.domain.models import Device


def _device(**kwargs) -> Device:  # noqa: ANN003
    values = {"display_name": "10.0.0.5", "primary_ip": "10.0.0.5", "hostname": None, "hostname_source": None}
    return Device(**{**values, **kwargs})


def test_unusable_names_are_dropped() -> None:
    for bad in (None, "", " ", "localhost", "10.0.0.5", "has space", "Omada Controller", "-x", "a" * 300):
        assert hostnames.clean(bad) is None, bad
    assert hostnames.clean("nas01.local.") == "nas01.local"
    assert hostnames.clean("MacBook-Pro") == "MacBook-Pro"


def test_a_name_fills_in_an_unnamed_device_and_its_display_name() -> None:
    device = _device()
    assert hostnames.apply_hostname(device, "nas01", "netbios") is True
    assert (device.hostname, device.hostname_source, device.display_name) == ("nas01", "netbios", "nas01")


def test_a_worse_source_never_replaces_a_better_one_but_a_better_one_does() -> None:
    device = _device()
    hostnames.apply_hostname(device, "from-dns", "dns")
    assert hostnames.apply_hostname(device, "from-tls", "tls") is False
    assert hostnames.apply_hostname(device, "from-mdns", "mdns") is False
    assert device.hostname == "from-dns"
    assert hostnames.apply_hostname(device, "from-ssh", "ssh") is True
    assert (device.hostname, device.display_name) == ("from-ssh", "from-ssh")
    assert hostnames.apply_hostname(device, "renamed", "ssh") is True  # the same source may refresh
    assert device.hostname == "renamed" and device.display_name == "renamed"


def test_a_name_a_human_chose_is_never_replaced() -> None:
    device = _device(hostname="my-box", hostname_source="manual", display_name="My Box")
    for source in ("ssh", "dns", "mdns", "netbios", "tls"):
        assert hostnames.apply_hostname(device, "other", source) is False
    assert (device.hostname, device.display_name) == ("my-box", "My Box")


def test_a_display_name_a_human_chose_is_kept_when_the_host_name_changes() -> None:
    device = _device(display_name="Living room NAS")
    hostnames.apply_hostname(device, "nas01", "dns")
    assert device.hostname == "nas01" and device.display_name == "Living room NAS"


def test_an_old_name_without_a_source_counts_as_a_dns_name() -> None:
    device = _device(hostname="old", hostname_source=None)
    assert hostnames.apply_hostname(device, "from-tls", "tls") is False
    assert hostnames.apply_hostname(device, "from-ssh", "ssh") is True


def _nbstat_reply(names: list[tuple[str, int, int]]) -> bytes:
    header = b"\x13\x37\x84\x00\x00\x00\x00\x01\x00\x00\x00\x00"
    answer = b"\x20" + b"CK" + b"A" * 30 + b"\x00" + b"\x00\x21\x00\x01\x00\x00\x00\x00"
    entries = b"".join(
        name.ljust(15).encode() + bytes([suffix]) + struct.pack(">H", flags) for name, suffix, flags in names
    )
    rdata = bytes([len(names)]) + entries + b"\x00" * 6
    return header + answer + struct.pack(">H", len(rdata)) + rdata


def test_the_netbios_computer_name_is_the_first_unique_00_entry() -> None:
    reply = _nbstat_reply(
        [("WORKGROUP", 0x00, 0x8400), ("FILESERVER", 0x00, 0x0400), ("FILESERVER", 0x20, 0x0400)]
    )
    assert device_names.parse_nbstat(reply) == "FILESERVER"
    assert device_names.parse_nbstat(b"garbage") is None
    assert device_names.parse_nbstat(_nbstat_reply([("WORKGROUP", 0x00, 0x8400)])) is None


class _Responder(asyncio.DatagramProtocol):
    def __init__(self, answer) -> None:  # noqa: ANN001
        self.answer = answer

    def connection_made(self, transport) -> None:  # noqa: ANN001
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # noqa: ANN001
        reply = self.answer(data)
        if reply is not None:
            self.transport.sendto(reply, addr)


async def _serve(answer, monkeypatch: pytest.MonkeyPatch, attribute: str) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _Responder(answer), local_addr=("127.0.0.1", 0)
    )
    monkeypatch.setattr(device_names, attribute, transport.get_extra_info("sockname")[1])
    return transport


@pytest.mark.asyncio
async def test_mdns_name_is_read_from_a_real_unicast_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(data: bytes) -> bytes:
        query = dns.message.from_wire(data)
        response = dns.message.make_response(query)
        response.answer.append(
            dns.rrset.from_text(query.question[0].name, 120, "IN", "PTR", "macbook.local.")
        )
        return response.to_wire()

    transport = await _serve(answer, monkeypatch, "MDNS_PORT")
    try:
        assert await real_mdns_name("127.0.0.1") == "macbook.local"
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_netbios_name_is_read_from_a_real_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = _nbstat_reply([("PRINTSRV", 0x00, 0x0400)])
    transport = await _serve(lambda data: reply, monkeypatch, "NETBIOS_PORT")
    try:
        assert await real_netbios_name("127.0.0.1") == "PRINTSRV"
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_a_silent_host_gives_no_name_after_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = await _serve(lambda data: None, monkeypatch, "MDNS_PORT")
    try:
        assert await real_mdns_name("127.0.0.1", timeout=0.2) is None
    finally:
        transport.close()


def test_the_lookups_work_on_uvloop_which_is_what_the_server_runs_on() -> None:
    """uvloop does not implement the loop's sock_sendto/sock_recvfrom; a lookup written with them raised
    NotImplementedError inside every host scan of the running app (the tests use the standard loop)."""
    uvloop = pytest.importorskip("uvloop")

    async def scenario() -> tuple[str | None, str | None]:
        loop = asyncio.get_running_loop()
        netbios_reply = _nbstat_reply([("PRINTSRV", 0x00, 0x0400)])
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Responder(lambda data: netbios_reply), local_addr=("127.0.0.1", 0)
        )
        device_names.NETBIOS_PORT = transport.get_extra_info("sockname")[1]
        try:
            return await real_netbios_name("127.0.0.1"), await real_mdns_name("127.0.0.1", timeout=0.2)
        finally:
            transport.close()
            device_names.NETBIOS_PORT = 137

    assert uvloop.run(scenario()) == ("PRINTSRV", None)


def test_serial_numbers_and_mac_addresses_are_not_host_names() -> None:
    for identifier in ("4ca0c3d25153d3e09e8c5fb8f6471230", "ecb5fafffe8b005c", "C429960BABC0"):
        assert hostnames.clean(identifier) is None
    assert hostnames.clean("cafe") == "cafe"  # short hex is still a plausible name
