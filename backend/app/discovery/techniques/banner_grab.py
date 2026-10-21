"""Service identification via plain TCP banner grabbing - no `nmap`, no
subprocess, no root/`CAP_NET_RAW`, nothing beyond stdlib `asyncio` sockets.

Many common services are "server speaks first": SSH, FTP, SMTP, POP3, IMAP,
and others send an identifying line the instant a TCP connection opens,
before the client sends anything (`SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.6`,
`220 ProFTPD 1.3.6 Server`, etc). Reading whatever a freshly-opened
connection sends, with a short timeout and no bytes written, is enough to
identify most non-HTTP services at a useful level - see docs/discovery.md.
This is the alternative to `nmap -sV`/`-O` for people who don't want to
install nmap or grant it raw-socket capabilities (`techniques/nmap_scan.py`
stays available as an optional extra for full OS fingerprinting).

HTTP(S)-like ports are deliberately skipped here (`http_probe.py` already
handles those - those services wait for a request, so a read-with-no-write
against them just burns the full timeout for nothing).
"""

import asyncio
import contextlib

READ_TIMEOUT_SECONDS = 1.5
MAX_BANNER_BYTES = 256


async def grab_banner(host: str, port: int, timeout: float = READ_TIMEOUT_SECONDS) -> str | None:
    """Returns a short printable banner, or None if the connection failed, the
    service closed without sending anything, or it's waiting for the client
    to speak first (most non-"server speaks first" protocols, including
    anything HTTP-like - use http_probe.py for those instead)."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    except (OSError, TimeoutError):
        return None

    try:
        data = await asyncio.wait_for(reader.read(MAX_BANNER_BYTES), timeout=timeout)
    except (OSError, TimeoutError):
        data = b""
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()

    if not data:
        return None
    return data.decode("utf-8", errors="replace").replace("\x00", "").strip() or None
