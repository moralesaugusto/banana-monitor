from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import asyncssh
import pytest
from pydantic import ValidationError

from app.integrations.base import TargetDescriptor
from app.integrations.generic_ssh.plugin import GenericSshPlugin, SshCredential

LOADAVG_OUTPUT = "0.10 0.20 0.30 1/200 12345\n"
MEMINFO_OUTPUT = "MemTotal:       16384000 kB\nMemAvailable:    8192000 kB\n"
DISKFREE_OUTPUT = "Filesystem 1B-blocks Used Available Use% Mounted on\n/dev/sda1 100 50 50 50% /\n"


class _NoAuthServer(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return False  # test server accepts any client without checking credentials


ssh_test_server_commands: dict[str, str] = {}
ssh_test_server_exit_codes: dict[str, int] = {}


async def _handle_process(process: asyncssh.SSHServerProcess) -> None:
    command = process.command or ""
    if command in ssh_test_server_commands:
        process.stdout.write(ssh_test_server_commands[command])
        process.exit(ssh_test_server_exit_codes.get(command, 0))
        return
    if command == "uname -s":
        process.stdout.write("Linux\n")
    elif "loadavg" in command:
        process.stdout.write(LOADAVG_OUTPUT)
    elif "meminfo" in command:
        process.stdout.write(MEMINFO_OUTPUT)
    elif command.startswith("df"):
        process.stdout.write(DISKFREE_OUTPUT)
    process.exit(ssh_test_server_exit_codes.get(command, 0))


@pytest.fixture
async def ssh_test_server() -> AsyncIterator[asyncssh.SSHAcceptor]:
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    server = await asyncssh.listen(
        "127.0.0.1",
        0,
        server_factory=_NoAuthServer,
        server_host_keys=[host_key],
        process_factory=_handle_process,
    )
    yield server
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_generic_ssh_plugin_polls_real_server(ssh_test_server: asyncssh.SSHAcceptor) -> None:
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    plugin = GenericSshPlugin()
    config = {
        "device_id": 1,
        "host": "127.0.0.1",
        "port": ssh_test_server.get_port(),
        "timeout_seconds": 5.0,
    }
    credential = {
        "username": "banana",
        "private_key": client_key.export_private_key().decode(),
    }
    target = TargetDescriptor(external_ref="1", display_name="test")

    result = await plugin.poll(config, credential, target)

    assert result.success is True, result.error_message
    assert result.metrics["load1"] == 0.10
    assert result.metrics["mem_used_percent"] == pytest.approx(50.0)
    assert result.metrics["disk_used_percent"] == 50.0
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_generic_ssh_plugin_polls_a_password_credential(ssh_test_server: asyncssh.SSHAcceptor) -> None:
    """A credential with no private_key, only a password, must work exactly like a key-based one -
    poll() and probe_credential() both support either credential shape (see SshCredential)."""
    plugin = GenericSshPlugin()
    config = {
        "device_id": 1,
        "host": "127.0.0.1",
        "port": ssh_test_server.get_port(),
        "timeout_seconds": 5.0,
    }
    credential = {"username": "banana", "password": "hunter2"}
    target = TargetDescriptor(external_ref="1", display_name="test")

    result = await plugin.poll(config, credential, target)

    assert result.success is True, result.error_message
    assert result.metrics["load1"] == 0.10


@pytest.mark.asyncio
async def test_generic_ssh_plugin_fails_against_closed_port() -> None:
    plugin = GenericSshPlugin()
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    config = {"device_id": 1, "host": "127.0.0.1", "port": 1, "timeout_seconds": 1.0}
    credential = {"username": "banana", "private_key": client_key.export_private_key().decode()}
    target = TargetDescriptor(external_ref="1", display_name="test")

    result = await plugin.poll(config, credential, target)

    assert result.success is False
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_generic_ssh_plugin_requires_credential() -> None:
    plugin = GenericSshPlugin()
    config = {"device_id": 1, "host": "127.0.0.1", "port": 22}
    target = TargetDescriptor(external_ref="1", display_name="test")

    result = await plugin.poll(config, None, target)

    assert result.success is False
    assert result.error_message == "No credential configured"


@pytest.mark.asyncio
async def test_the_host_key_is_pinned_on_first_use_and_a_different_server_is_refused(
    ssh_test_server: asyncssh.SSHAcceptor,
) -> None:
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    credential = {"username": "banana", "private_key": client_key.export_private_key().decode()}
    config = {"device_id": 1, "host": "127.0.0.1", "port": ssh_test_server.get_port(), "timeout_seconds": 5.0}
    target = TargetDescriptor(external_ref="1", display_name="x", device_id=1)

    first = await GenericSshPlugin().poll(config, credential, target)
    pinned = first.learned_config["host_key"]
    assert pinned.startswith("ssh-ed25519 ")

    os_family = first.learned_config["os_family"]
    again = await GenericSshPlugin().poll(
        {**config, "host_key": pinned, "os_family": os_family}, credential, target
    )
    assert again.success is True and again.learned_config == {}

    impostor = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode().strip()
    refused = await GenericSshPlugin().poll(
        {**config, "host_key": impostor, "auto_repin_host_key": False}, credential, target
    )
    assert refused.success is False
    assert "does not match the pinned key" in (refused.error_message or "")


@pytest.mark.asyncio
async def test_a_changed_host_key_is_repinned_automatically_by_default(
    ssh_test_server: asyncssh.SSHAcceptor,
) -> None:
    """auto_repin_host_key defaults on: a real server answering with a key that doesn't match the
    pinned one (e.g. its IP was reassigned to a different machine) is re-pinned and polled, not refused."""
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    credential = {"username": "banana", "private_key": client_key.export_private_key().decode()}
    config = {"device_id": 1, "host": "127.0.0.1", "port": ssh_test_server.get_port(), "timeout_seconds": 5.0}
    target = TargetDescriptor(external_ref="1", display_name="x")

    stale = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode().strip()
    result = await GenericSshPlugin().poll({**config, "host_key": stale}, credential, target)

    assert result.success is True, result.error_message
    assert result.learned_config["host_key"] != stale
    assert result.learned_config["host_key"].startswith("ssh-ed25519 ")


@pytest.mark.asyncio
async def test_os_detection_runs_once_and_is_cached_in_learned_config(
    ssh_test_server: asyncssh.SSHAcceptor,
) -> None:
    key = asyncssh.generate_private_key("ssh-ed25519")
    credential = {"username": "banana", "private_key": key.export_private_key().decode()}
    config = {"device_id": 1, "host": "127.0.0.1", "port": ssh_test_server.get_port(), "timeout_seconds": 5.0}
    target = TargetDescriptor(external_ref="1", display_name="x")

    first = await GenericSshPlugin().poll(config, credential, target)
    assert first.success is True, first.error_message
    assert first.learned_config.get("os_family") == "linux"

    again = await GenericSshPlugin().poll({**config, "os_family": "linux"}, credential, target)
    assert again.success is True
    assert "os_family" not in again.learned_config  # already known - not re-detected


@pytest.mark.asyncio
async def test_unrecognized_os_falls_back_to_linux_commands(
    ssh_test_server: asyncssh.SSHAcceptor,
) -> None:
    """A uname answer other than "Linux" still gets the only implemented command family, logged as a
    warning rather than failing the poll outright - see _detect_os_family's docstring."""
    ssh_test_server_commands["uname -s"] = "FreeBSD\n"
    key = asyncssh.generate_private_key("ssh-ed25519")
    credential = {"username": "banana", "private_key": key.export_private_key().decode()}
    config = {"device_id": 1, "host": "127.0.0.1", "port": ssh_test_server.get_port(), "timeout_seconds": 5.0}
    target = TargetDescriptor(external_ref="1", display_name="x")

    result = await GenericSshPlugin().poll(config, credential, target)

    assert result.success is True, result.error_message
    assert result.learned_config.get("os_family") == "linux"
    assert result.metrics["load1"] == 0.10  # the Linux command set still ran and was parsed


@pytest.mark.asyncio
async def test_windows_host_is_detected_and_polled_with_wmic_commands(
    ssh_test_server: asyncssh.SSHAcceptor,
) -> None:
    """Win32-OpenSSH's default shell is cmd.exe, which has no `uname` builtin - a nonzero exit is the
    detection signal, not a particular error string (see _detect_os_family)."""
    ssh_test_server_exit_codes["uname -s"] = 1
    ssh_test_server_commands["wmic cpu get loadpercentage /value"] = "\r\nLoadPercentage=7\r\n\r\n"
    ssh_test_server_commands["wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value"] = (
        "\r\nFreePhysicalMemory=2097152\r\nTotalVisibleMemorySize=8388608\r\n\r\n"
    )
    ssh_test_server_commands["wmic logicaldisk where DeviceID='C:' get Size,FreeSpace /value"] = (
        "\r\nFreeSpace=40000000000\r\nSize=100000000000\r\n\r\n"
    )
    ssh_test_server_commands["hostname"] = "WIN-TESTHOST\r\n"
    key = asyncssh.generate_private_key("ssh-ed25519")
    credential = {"username": "banana", "private_key": key.export_private_key().decode()}
    config = {"device_id": 1, "host": "127.0.0.1", "port": ssh_test_server.get_port(), "timeout_seconds": 5.0}
    target = TargetDescriptor(external_ref="1", display_name="x")

    result = await GenericSshPlugin().poll(config, credential, target)

    assert result.success is True, result.error_message
    assert result.learned_config.get("os_family") == "windows"
    assert result.hostname == "WIN-TESTHOST"
    assert result.metrics["load1"] == 7.0
    assert result.metrics["mem_total_kb"] == 8388608.0
    assert result.metrics["mem_used_percent"] == pytest.approx(75.0)
    assert result.metrics["disk_used_percent"] == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_the_hosts_own_name_is_reported_and_wins_over_a_dns_name(
    ssh_test_server: asyncssh.SSHAcceptor,
) -> None:
    from app.discovery.hostnames import apply_hostname
    from app.domain.models import Device

    ssh_test_server_commands["hostname"] = "pve-node1\n"  # the command is the literal string `hostname`
    key = asyncssh.generate_private_key("ssh-ed25519")
    credential = {"username": "banana", "private_key": key.export_private_key().decode()}
    config = {"device_id": 1, "host": "127.0.0.1", "port": ssh_test_server.get_port(), "timeout_seconds": 5.0}
    target = TargetDescriptor(external_ref="1", display_name="x")
    result = await GenericSshPlugin().poll(config, credential, target)
    assert result.success and result.hostname == "pve-node1"

    device = Device(display_name="10.0.0.5", primary_ip="10.0.0.5")
    apply_hostname(device, "from-dns", "dns")
    assert apply_hostname(device, result.hostname, "ssh") is True
    assert (device.hostname, device.hostname_source) == ("pve-node1", "ssh")


@pytest.mark.asyncio
async def test_wallet_entry_has_no_host_and_lists_no_targets() -> None:
    """A credential-wallet entry (no host, no device_id) is a valid config but has nothing to poll
    until discovery finds it a host - see docs/credentials.md's "Credential wallet" section."""
    plugin = GenericSshPlugin()
    credential = {"username": "banana", "private_key": "irrelevant"}

    result = await plugin.validate_config({}, credential)
    assert result.ok is True

    assert await plugin.list_targets({}, credential) == []


@pytest.mark.asyncio
async def test_host_without_device_id_is_rejected() -> None:
    plugin = GenericSshPlugin()
    result = await plugin.validate_config({"host": "10.0.0.5"}, {"username": "banana", "password": "x"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_probe_credential_succeeds_against_real_server(ssh_test_server: asyncssh.SSHAcceptor) -> None:
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    credential = {"username": "banana", "private_key": client_key.export_private_key().decode()}

    ok = await GenericSshPlugin().probe_credential(credential, "127.0.0.1", ssh_test_server.get_port())

    assert ok is True


@pytest.mark.asyncio
async def test_probe_credential_succeeds_with_a_password_against_real_server(
    ssh_test_server: asyncssh.SSHAcceptor,
) -> None:
    credential = {"username": "banana", "password": "hunter2"}

    ok = await GenericSshPlugin().probe_credential(credential, "127.0.0.1", ssh_test_server.get_port())

    assert ok is True


@pytest.mark.asyncio
async def test_probe_credential_fails_against_closed_port() -> None:
    credential = {"username": "banana", "password": "wrong"}

    ok = await GenericSshPlugin().probe_credential(credential, "127.0.0.1", 1)

    assert ok is False


@pytest.mark.asyncio
async def test_validate_config_makes_a_real_connection_when_host_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """validate_config() now gives fail-fast feedback instead of silently creating a broken integration -
    see docs/decisions.md."""
    plugin = GenericSshPlugin()
    credential = {"username": "banana", "private_key": "irrelevant"}
    config = {"device_id": 1, "host": "10.77.0.50", "port": 22}

    monkeypatch.setattr(plugin, "probe_credential", AsyncMock(return_value=False))
    failed = await plugin.validate_config(config, credential)
    assert failed.ok is False
    assert "10.77.0.50:22" in (failed.message or "")

    monkeypatch.setattr(plugin, "probe_credential", AsyncMock(return_value=True))
    assert (await plugin.validate_config(config, credential)).ok is True


@pytest.mark.asyncio
async def test_validate_config_skips_the_live_check_for_a_wallet_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = GenericSshPlugin()
    credential = {"username": "banana", "private_key": "irrelevant"}

    probe = AsyncMock(side_effect=AssertionError("probe_credential must not be called for a wallet entry"))
    monkeypatch.setattr(plugin, "probe_credential", probe)

    result = await plugin.validate_config({}, credential)

    assert result.ok is True
    probe.assert_not_called()


def test_ssh_credential_accepts_a_private_key_or_a_password() -> None:
    SshCredential.model_validate({"username": "banana", "private_key": "x"})
    SshCredential.model_validate({"username": "banana", "password": "x"})


def test_ssh_credential_rejects_neither_key_nor_password() -> None:
    with pytest.raises(ValidationError, match="either private_key or password must be set"):
        SshCredential.model_validate({"username": "banana"})
