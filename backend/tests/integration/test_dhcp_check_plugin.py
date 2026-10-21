import asyncio
import struct
from collections.abc import AsyncIterator

import pytest

from app.integrations.base import TargetDescriptor
from app.integrations.dhcp_check import plugin as dhcp_plugin
from app.integrations.dhcp_check.plugin import DhcpCheckPlugin

_MAGIC_COOKIE = b"\x63\x82\x53\x63"
_BOOTP_HEADER_LEN = 236


class _FakeDhcpServerProtocol(asyncio.DatagramProtocol):
    """A minimal fake DHCP server: parses the incoming DHCPDISCOVER's
    transaction id and replies with a well-formed DHCPOFFER carrying the same
    xid, addressed back to whichever address/port sent the discover (an
    ephemeral client port in this plugin's design - see the "known
    limitation" note in docs/integrations.md about why this differs from a
    strictly RFC-compliant server, which replies to UDP port 68)."""

    def __init__(self, *, respond: bool = True, garbage_reply: bool = False) -> None:
        self._respond = respond
        self._garbage_reply = garbage_reply
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        assert self.transport is not None
        if not self._respond:
            return
        if self._garbage_reply:
            self.transport.sendto(b"not a dhcp packet", addr)
            return
        _op, _htype, _hlen, _hops, xid = struct.unpack("!BBBBI", data[:8])
        self.transport.sendto(_build_offer(xid), addr)


def _build_offer(xid: int) -> bytes:
    header = struct.pack(
        "!BBBBIHH4s4s4s4s16s192x4s",
        2,  # BOOTREPLY
        1,  # htype ethernet
        6,  # hlen
        0,  # hops
        xid,
        0,  # secs
        0,  # flags
        b"\x00\x00\x00\x00",  # ciaddr
        b"\xc0\xa8\x01\x64",  # yiaddr - 192.168.1.100
        b"\x00\x00\x00\x00",  # siaddr
        b"\x00\x00\x00\x00",  # giaddr
        b"\x00" * 16,  # chaddr
        _MAGIC_COOKIE,
    )
    options = bytes([53, 1, 2, 255])  # message type = DHCPOFFER, then End
    return header + options


@pytest.fixture
async def fake_dhcp_server() -> AsyncIterator[int]:
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        _FakeDhcpServerProtocol, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    try:
        yield port
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_dhcp_check_receives_offer(
    fake_dhcp_server: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dhcp_plugin, "DHCP_SERVER_PORT", fake_dhcp_server)
    plugin = DhcpCheckPlugin()
    config = {"host": "127.0.0.1", "timeout_seconds": 2.0}
    target = TargetDescriptor(external_ref="1", display_name="dhcp")

    result = await plugin.poll(config, None, target)

    assert result.success is True, result.error_message
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_dhcp_check_times_out_when_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _FakeDhcpServerProtocol(respond=False), local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    try:
        monkeypatch.setattr(dhcp_plugin, "DHCP_SERVER_PORT", port)
        plugin = DhcpCheckPlugin()
        config = {"host": "127.0.0.1", "timeout_seconds": 0.3}
        target = TargetDescriptor(external_ref="1", display_name="dhcp")

        result = await plugin.poll(config, None, target)

        assert result.success is False
        assert "timed out" in (result.error_message or "").lower()
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_dhcp_check_rejects_garbage_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _FakeDhcpServerProtocol(garbage_reply=True), local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    try:
        monkeypatch.setattr(dhcp_plugin, "DHCP_SERVER_PORT", port)
        plugin = DhcpCheckPlugin()
        config = {"host": "127.0.0.1", "timeout_seconds": 1.0}
        target = TargetDescriptor(external_ref="1", display_name="dhcp")

        result = await plugin.poll(config, None, target)

        assert result.success is False
        assert result.error_message is not None
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_validate_config_rejects_missing_host() -> None:
    plugin = DhcpCheckPlugin()

    result = await plugin.validate_config({}, None)

    assert result.ok is False
