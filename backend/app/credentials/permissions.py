import os
import stat
from pathlib import Path

from app.logging_setup import get_logger

logger = get_logger(__name__)


def enforce_private_file(path: Path) -> None:
    """Ensure a sensitive file is only readable/writable by its owner (0600)."""
    if not path.exists():
        return

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        logger.warning("file_permissions_fixed", path=str(path), previous_mode=oct(mode))
        os.chmod(path, 0o600)
