import asyncio

import pytest

from app.discovery.techniques import banner_grab


async def _serve_banner(banner: bytes) -> tuple[asyncio.AbstractServer, int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(banner)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


@pytest.mark.asyncio
async def test_grab_banner_reads_server_speaks_first_text() -> None:
    server, port = await _serve_banner(b"SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.6\r\n")
    try:
        banner = await banner_grab.grab_banner("127.0.0.1", port)
        assert banner == "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.6"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_grab_banner_returns_none_when_nothing_is_sent() -> None:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(0.05)
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        banner = await banner_grab.grab_banner("127.0.0.1", port, timeout=0.3)
        assert banner is None
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_grab_banner_decodes_non_utf8_bytes_without_raising() -> None:
    server, port = await _serve_banner(b"\xffMySQL binary handshake\x00")
    try:
        banner = await banner_grab.grab_banner("127.0.0.1", port)
        assert banner is not None
        assert "MySQL binary handshake" in banner
    finally:
        server.close()
        await server.wait_closed()
