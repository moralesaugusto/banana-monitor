"""Asking a device for its own name: mDNS (`.local`, Apple/Linux/printers) and NetBIOS (Windows, Samba,
NAS boxes). Both are one UDP question sent straight to the device, so they need no multicast and no
privileges; a device that does not speak the protocol simply does not answer."""

import asyncio
import struct
from typing import cast

import dns.exception
import dns.message
import dns.rdatatype
import dns.reversename

from app.discovery.techniques import dns_probe

MDNS_PORT = 5353
NETBIOS_PORT = 137
# NBSTAT question for the wildcard name "*": 12-byte header, the encoded name, type NBSTAT (0x21), class IN.
_NBSTAT_QUERY = (
    b"\x13\x37\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    + b"\x20"
    + b"CK"
    + b"A" * 30
    + b"\x00"
    + b"\x00\x21\x00\x01"
)


class _Reply(asyncio.DatagramProtocol):
    """Sends one datagram and keeps the first answer."""

    def __init__(self, payload: bytes, answer: "asyncio.Future[bytes]") -> None:
        self._payload = payload
        self._answer = answer

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        # uvloop's transport is not an asyncio.DatagramTransport subclass, so no isinstance check here.
        cast(asyncio.DatagramTransport, transport).sendto(self._payload)

    def datagram_received(self, data: bytes, addr: tuple[str | int, ...]) -> None:
        if not self._answer.done():
            self._answer.set_result(data)

    def error_received(self, exc: Exception) -> None:
        if not self._answer.done():
            self._answer.set_exception(exc)


async def _udp_exchange(ip: str, port: int, payload: bytes, timeout: float) -> bytes | None:
    """One question, one answer. Built on a datagram endpoint rather than the loop's `sock_sendto`, which
    uvloop (the loop uvicorn runs on) does not implement."""
    loop = asyncio.get_running_loop()
    answer: asyncio.Future[bytes] = loop.create_future()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Reply(payload, answer), remote_addr=(ip, port)
        )
    except OSError:
        return None
    try:
        return await asyncio.wait_for(answer, timeout)
    except (OSError, TimeoutError):
        return None
    finally:
        transport.close()


async def mdns_name(ip: str, timeout: float = 1.0) -> str | None:
    """Asks the device for the name behind its own address (`x.x.x.x.in-addr.arpa`), the way `avahi-resolve
    -a` does. A query from a source port other than 5353 is answered by unicast (RFC 6762 section 6.7)."""
    query = dns.message.make_query(dns.reversename.from_address(ip), dns.rdatatype.PTR)
    data = await _udp_exchange(ip, MDNS_PORT, query.to_wire(), timeout)
    if data is None:
        return None
    try:
        response = dns.message.from_wire(data)
    except (dns.exception.DNSException, ValueError):
        return None
    for rrset in response.answer:
        if rrset.rdtype == dns.rdatatype.PTR:
            return str(rrset[0].target).rstrip(".")
    return None


def parse_nbstat(data: bytes) -> str | None:
    """The computer name from a NetBIOS node status reply: the first name with suffix 0x00 that is not a
    group name. Layout: 12-byte header, answer name (34 bytes), type/class/ttl/rdlength (10), name count,
    then 18 bytes per name (15 characters, 1 suffix byte, 2 flag bytes)."""
    if len(data) < 57 or data[3] & 0x0F:
        return None
    count = data[56]
    for index in range(count):
        start = 57 + index * 18
        entry = data[start : start + 18]
        if len(entry) < 18:
            break
        name, suffix = entry[:15].decode("ascii", "replace").strip(), entry[15]
        (flags,) = struct.unpack(">H", entry[16:18])
        if suffix == 0x00 and not flags & 0x8000 and name:
            return name
    return None


async def netbios_name(ip: str, timeout: float = 1.0) -> str | None:
    data = await _udp_exchange(ip, NETBIOS_PORT, _NBSTAT_QUERY, timeout)
    return parse_nbstat(data) if data else None


async def lookup_names(ip: str, dns_server: str | None) -> list[tuple[str, str]]:
    """Every (name, source) the network can give for this address; the caller keeps the best."""
    dns_name, mdns, netbios = await asyncio.gather(
        dns_probe.reverse_dns(ip, server=dns_server or None), mdns_name(ip), netbios_name(ip)
    )
    found = [("dns", dns_name), ("mdns", mdns), ("netbios", netbios)]
    return [(name, source) for source, name in found if name]
