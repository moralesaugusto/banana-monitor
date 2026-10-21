import asyncio
import contextlib

COMMON_PORTS: list[int] = [
    22,
    53,  # DNS - see docs/discovery.md for why a TCP connect-scan signal was chosen over an active probe
    80,
    443,
    445,
    3000,  # AdGuard Home
    3389,
    5000,
    8006,
    8043,  # Omada Controller (HTTPS)
    8080,
    8123,
    8443,
    8581,  # Homebridge
    8843,  # Omada Controller (HTTPS, alternate)
    5986,  # WinRM (HTTPS)
]


ALL_PORTS: list[int] = list(range(1, 65536))


async def scan_ports(
    host: str, ports: list[int] | None = None, timeout: float = 0.5, concurrency: int = 256
) -> list[int]:
    """Connect-scan: the small curated list by default, or whatever `ports` says. At most `concurrency`
    sockets are open at once, so a sweep of every port stays well below the file descriptor limit."""
    targets = ports if ports is not None else COMMON_PORTS
    limit = asyncio.Semaphore(concurrency)

    async def check(port: int) -> int | None:
        try:
            async with limit:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        except (OSError, TimeoutError):
            return None
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        return port

    results = await asyncio.gather(*(check(port) for port in targets))
    return sorted(port for port in results if port is not None)
