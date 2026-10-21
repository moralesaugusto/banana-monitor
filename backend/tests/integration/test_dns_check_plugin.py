import asyncio
from collections.abc import AsyncIterator

import dns.message
import dns.rdatatype
import dns.rrset
import pytest

from app.integrations.base import TargetDescriptor
from app.integrations.dns_check.plugin import DnsCheckPlugin


class _FakeDnsProtocol(asyncio.DatagramProtocol):
    """Answers any A query with 127.0.0.1, mirroring the "fake server" testing
    philosophy used for generic_ssh (asyncssh's own server API) and proxmox
    (respx canned fixtures) - here it's a minimal real DNS responder built
    with dnspython's own message classes rather than mocking the resolver."""

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        assert self.transport is not None
        request = dns.message.from_wire(data)
        response = dns.message.make_response(request)
        question = request.question[0]
        rrset = dns.rrset.from_text(question.name, 60, "IN", dns.rdatatype.A, "127.0.0.1")
        response.answer.append(rrset)
        self.transport.sendto(response.to_wire(), addr)


@pytest.fixture
async def fake_dns_server() -> AsyncIterator[int]:
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        _FakeDnsProtocol, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    try:
        yield port
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_dns_check_resolves_successfully(fake_dns_server: int) -> None:
    plugin = DnsCheckPlugin()
    config = {
        "host": "127.0.0.1",
        "port": fake_dns_server,
        "query_name": "example.com",
        "timeout_seconds": 2.0,
    }
    target = TargetDescriptor(external_ref="1", display_name="dns")

    result = await plugin.poll(config, None, target)

    assert result.success is True, result.error_message
    assert result.latency_ms is not None
    assert result.metrics["response_time_ms"] > 0


@pytest.mark.asyncio
async def test_dns_check_times_out_against_unresponsive_host() -> None:
    plugin = DnsCheckPlugin()
    # Port 1 has nothing listening - the resolve() call will fail fast
    # (connection refused) or time out, either way success must be False.
    config = {"host": "127.0.0.1", "port": 1, "query_name": "example.com", "timeout_seconds": 0.5}
    target = TargetDescriptor(external_ref="1", display_name="dns")

    result = await plugin.poll(config, None, target)

    assert result.success is False
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_dns_check_reports_nxdomain_as_failure(fake_dns_server: int) -> None:
    """The fake server always answers A queries with an rrset, so to exercise
    the failure path for a "real" DNS error we point at a record type the
    fake server doesn't special-case and instead returns no answer for -
    dnspython raises NoAnswer, a DNSException subclass, which the plugin must
    convert into success=False rather than raising."""

    class _NoAnswerProtocol(_FakeDnsProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            assert self.transport is not None
            request = dns.message.from_wire(data)
            response = dns.message.make_response(request)
            # No answer records appended - dnspython treats this as NoAnswer.
            self.transport.sendto(response.to_wire(), addr)

    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        _NoAnswerProtocol, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    try:
        plugin = DnsCheckPlugin()
        config = {
            "host": "127.0.0.1",
            "port": port,
            "query_name": "example.com",
            "timeout_seconds": 2.0,
        }
        target = TargetDescriptor(external_ref="1", display_name="dns")

        result = await plugin.poll(config, None, target)

        assert result.success is False
        assert result.error_message is not None
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_validate_config_rejects_missing_host() -> None:
    plugin = DnsCheckPlugin()

    result = await plugin.validate_config({}, None)

    assert result.ok is False
