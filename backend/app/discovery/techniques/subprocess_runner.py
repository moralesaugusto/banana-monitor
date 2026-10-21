import asyncio
from collections.abc import Awaitable, Callable

SubprocessRunner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]
"""Injectable so tests can fake ping/ip-neigh output without real network access."""


async def default_subprocess_runner(args: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
