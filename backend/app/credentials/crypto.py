import json
import os
import stat
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings
from app.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_MASTER_KEY_FILENAME = "master.key"


class MasterKeyError(RuntimeError):
    pass


def _default_master_key_path(settings: Settings) -> Path:
    """A key a previous version put next to the databases keeps being used; a new install generates it
    in a `secrets` directory beside the data directory, so copying or backing up `data/` does not copy
    the key together with the ciphertext it protects."""
    legacy = settings.data_dir / DEFAULT_MASTER_KEY_FILENAME
    if legacy.exists():
        return legacy
    return settings.data_dir.resolve().parent / "secrets" / DEFAULT_MASTER_KEY_FILENAME


def _read_key_file(path: Path) -> bytes:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise MasterKeyError(
            f"{path} is readable by other users (mode {oct(mode)}); run `chmod 600 {path}` and start again"
        )
    return path.read_bytes().strip()


def _generate_and_store_key(path: Path) -> bytes:
    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(key)
    os.chmod(path, 0o600)
    logger.warning(
        "master_key_generated",
        path=str(path),
        note="Back this file up. Losing it makes all stored credentials unrecoverable.",
    )
    return key


def master_key_path(settings: Settings) -> Path:
    return settings.master_key_file or _default_master_key_path(settings)


def load_master_key(settings: Settings) -> bytes:
    if settings.master_key:
        return settings.master_key.encode()

    path = master_key_path(settings)
    if path.exists():
        return _read_key_file(path)
    return _generate_and_store_key(path)


class SecretBox:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, payload: dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(payload).encode())

    def decrypt(self, ciphertext: bytes) -> dict[str, Any]:
        try:
            plaintext = self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise MasterKeyError("Unable to decrypt credential: master key mismatch") from exc
        result: dict[str, Any] = json.loads(plaintext)
        return result


@lru_cache
def get_secret_box() -> SecretBox:
    return SecretBox(load_master_key(get_settings()))
