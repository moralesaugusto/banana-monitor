from app.discovery.techniques.subprocess_runner import SubprocessRunner, default_subprocess_runner
from app.logging_setup import get_logger

logger = get_logger(__name__)
_warned_missing = False


async def ping_host(
    host: str, timeout: float = 1.0, runner: SubprocessRunner = default_subprocess_runner
) -> bool:
    """True if the host answers one ping. A system without `ping` installed answers False for every
    host (liveness then comes from the TCP probes) rather than failing the caller."""
    global _warned_missing
    try:
        returncode, _, _ = await runner(["ping", "-c", "1", "-W", str(max(1, int(timeout))), host])
    except FileNotFoundError:
        if not _warned_missing:
            _warned_missing = True
            logger.warning("ping_not_installed", hint="install ping; hosts are found by open ports only")
        return False
    return returncode == 0
