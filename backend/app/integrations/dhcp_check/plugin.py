import asyncio
import random
import struct
import time
from typing import Any, ClassVar

from pydantic import BaseModel

from app.integrations.base import (
    DiscoveredItem,
    PollResult,
    TargetDescriptor,
    ValidationResult,
    clean_validation_message,
)

DHCP_SERVER_PORT = 67
"""Module-level so tests can monkeypatch it to point at an in-process fake
DHCP server bound to a non-privileged ephemeral port."""

_BOOTREQUEST = 1
_BOOTREPLY = 2
_HTYPE_ETHERNET = 1
_HLEN_ETHERNET = 6
_MAGIC_COOKIE = b"\x63\x82\x53\x63"
_OPTION_MESSAGE_TYPE = 53
_OPTION_END = 255
_OPTION_PAD = 0
_DHCPDISCOVER = 1
_DHCPOFFER = 2
_BOOTP_HEADER_LEN = 236  # up through sname/file, before the magic cookie


class DhcpCheckConfig(BaseModel):
    host: str
    timeout_seconds: float = 2.0
    interval_seconds: float = 30.0


class DhcpCheckPlugin:
    """Best-effort DHCP server health probe.

    Sends a unicast DHCPDISCOVER (RFC 2131) to host:67 from an ephemeral UDP
    source port and waits for any DHCPOFFER reply carrying the same
    transaction ID. This is inherently best-effort: RFC 2131 has the server
    reply to UDP port 68 (the standard DHCP client port), not to an arbitrary
    ephemeral source port, so a strictly RFC-compliant server/firewall may
    never reply here even though it is healthy - see docs/integrations.md for
    the full "known limitation" note. Service-backed like http_tcp/dns - no
    credential, no Device auto-provisioning.
    """

    type_key: ClassVar[str] = "dhcp"
    display_name: ClassVar[str] = "DHCP Reachability Check"
    config_schema: ClassVar[type[BaseModel]] = DhcpCheckConfig
    credential_schema: ClassVar[type[BaseModel] | None] = None

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            DhcpCheckConfig.model_validate(config)
        except ValueError as exc:
            return ValidationResult(ok=False, message=clean_validation_message(exc))
        return ValidationResult(ok=True)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        return []

    async def discover(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[DiscoveredItem]:
        return []

    async def poll(
        self,
        config: dict[str, Any],
        credential: dict[str, Any] | None,
        target: TargetDescriptor,
    ) -> PollResult:
        cfg = DhcpCheckConfig.model_validate(config)
        try:
            success, latency_ms, error = await _probe(cfg.host, cfg.timeout_seconds)
        except OSError as exc:
            return PollResult(success=False, error_message=str(exc))
        return PollResult(success=success, latency_ms=latency_ms, error_message=error)


class _DiscoverClientProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_reply: "asyncio.Future[bytes]") -> None:
        self._on_reply = on_reply

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not self._on_reply.done():
            self._on_reply.set_result(data)

    def error_received(self, exc: Exception) -> None:
        if not self._on_reply.done():
            self._on_reply.set_exception(exc)


async def _probe(host: str, timeout: float) -> tuple[bool, float, str | None]:
    xid = random.randint(0, 0xFFFFFFFF)
    packet = _build_discover_packet(xid, _random_mac())

    loop = asyncio.get_running_loop()
    on_reply: asyncio.Future[bytes] = loop.create_future()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _DiscoverClientProtocol(on_reply),
        local_addr=("0.0.0.0", 0),
        remote_addr=(host, DHCP_SERVER_PORT),
    )

    started = time.monotonic()
    try:
        transport.sendto(packet)
        try:
            data = await asyncio.wait_for(on_reply, timeout=timeout)
        except TimeoutError:
            latency_ms = (time.monotonic() - started) * 1000
            return False, latency_ms, "Timed out waiting for a DHCPOFFER reply"

        latency_ms = (time.monotonic() - started) * 1000
        if not _is_dhcp_offer(data, xid):
            return False, latency_ms, "Received a reply that was not a valid DHCPOFFER"
        return True, latency_ms, None
    finally:
        transport.close()


def _random_mac() -> bytes:
    """A synthetic locally-administered MAC for the probe's chaddr field - this
    is a synthetic health check, not a real client requesting a lease, so the
    address only needs to be well-formed, not tied to a real interface."""
    mac = bytearray(random.getrandbits(8) for _ in range(6))
    mac[0] = (mac[0] & 0xFE) | 0x02  # locally administered, unicast
    return bytes(mac)


def _build_discover_packet(xid: int, mac: bytes) -> bytes:
    chaddr = mac + b"\x00" * (16 - len(mac))
    header = struct.pack(
        "!BBBBIHH4s4s4s4s16s192x4s",
        _BOOTREQUEST,
        _HTYPE_ETHERNET,
        _HLEN_ETHERNET,
        0,  # hops
        xid,
        0,  # secs
        0x8000,  # flags: broadcast bit set (we have no IP of our own yet)
        b"\x00\x00\x00\x00",  # ciaddr
        b"\x00\x00\x00\x00",  # yiaddr
        b"\x00\x00\x00\x00",  # siaddr
        b"\x00\x00\x00\x00",  # giaddr
        chaddr,
        _MAGIC_COOKIE,
    )
    options = bytes([_OPTION_MESSAGE_TYPE, 1, _DHCPDISCOVER, _OPTION_END])
    return header + options


def _is_dhcp_offer(data: bytes, expected_xid: int) -> bool:
    if len(data) < _BOOTP_HEADER_LEN + len(_MAGIC_COOKIE):
        return False
    op, _htype, _hlen, _hops, xid = struct.unpack("!BBBBI", data[:8])
    if op != _BOOTREPLY or xid != expected_xid:
        return False
    cookie_start = _BOOTP_HEADER_LEN
    if data[cookie_start : cookie_start + 4] != _MAGIC_COOKIE:
        return False

    options = data[cookie_start + 4 :]
    i = 0
    while i < len(options):
        opt_type = options[i]
        if opt_type == _OPTION_END:
            break
        if opt_type == _OPTION_PAD:
            i += 1
            continue
        if i + 1 >= len(options):
            break
        opt_len = options[i + 1]
        opt_val = options[i + 2 : i + 2 + opt_len]
        if opt_type == _OPTION_MESSAGE_TYPE and opt_val == bytes([_DHCPOFFER]):
            return True
        i += 2 + opt_len
    return False
