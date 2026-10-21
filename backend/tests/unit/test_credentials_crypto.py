import stat

import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.credentials.crypto import MasterKeyError, SecretBox, load_master_key


def test_round_trip_encrypt_decrypt() -> None:
    box = SecretBox(Fernet.generate_key())
    secret = {"username": "root", "password": "hunter2"}

    ciphertext = box.encrypt(secret)
    assert b"hunter2" not in ciphertext

    assert box.decrypt(ciphertext) == secret


def test_wrong_key_fails_to_decrypt() -> None:
    box_a = SecretBox(Fernet.generate_key())
    box_b = SecretBox(Fernet.generate_key())

    ciphertext = box_a.encrypt({"token": "abc"})

    with pytest.raises(MasterKeyError):
        box_b.decrypt(ciphertext)


def test_load_master_key_generates_and_persists(tmp_path) -> None:
    settings = get_settings()
    assert settings.data_dir == tmp_path

    key_path = settings.master_key_file
    assert key_path is not None and not key_path.exists()

    key1 = load_master_key(settings)
    assert key_path.exists()
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600

    key2 = load_master_key(settings)
    assert key1 == key2


def test_a_new_install_keeps_the_key_outside_the_data_directory(tmp_path) -> None:
    from app.config import Settings
    from app.credentials.crypto import _default_master_key_path

    data = tmp_path / "data"
    settings = Settings(data_dir=data, master_key_file=None)
    assert _default_master_key_path(settings) == tmp_path / "secrets" / "master.key"


def test_an_existing_key_next_to_the_databases_keeps_being_used(tmp_path) -> None:
    from app.config import Settings
    from app.credentials.crypto import _default_master_key_path

    data = tmp_path / "data"
    data.mkdir()
    (data / "master.key").write_bytes(Fernet.generate_key())
    assert _default_master_key_path(Settings(data_dir=data, master_key_file=None)) == data / "master.key"


def test_a_key_file_other_users_can_read_stops_startup(tmp_path) -> None:
    from app.config import Settings

    key_file = tmp_path / "k"
    key_file.write_bytes(Fernet.generate_key())
    key_file.chmod(0o644)
    with pytest.raises(MasterKeyError, match="chmod 600"):
        load_master_key(Settings(data_dir=tmp_path, master_key_file=key_file))
    key_file.chmod(0o600)
    load_master_key(Settings(data_dir=tmp_path, master_key_file=key_file))
