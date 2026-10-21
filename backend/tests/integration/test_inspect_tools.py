import json
from collections.abc import AsyncIterator

import asyncssh
import pytest
from sqlalchemy import select

from app.credentials.crypto import get_secret_box
from app.credentials.models import CredentialsBase
from app.credentials.service import CredentialService
from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_site
from app.domain.enums import CredentialType, DeviceType, ServiceType
from app.domain.models import Base as AppBase
from app.domain.models import Device, Event, Integration, Service
from app.integrations.generic_ssh import hostkey
from app.llm import agent_tools

SECRET = "-----SECRET-KEY-MATERIAL-----"
SERVER_OUTPUT = {
    "uname -a": "Linux lab 6.1.0\n",
    "apt list --upgradable": "openssl/stable 3.0.2 [upgradable]\n",
}
commands_run: list[str] = []


async def _handle(process: asyncssh.SSHServerProcess) -> None:
    command = process.command or ""
    commands_run.append(command)
    if command.startswith("if command -v apt-get"):
        process.stdout.write("apt\n")
    elif command.startswith("sudo -n apt-get"):
        process.stdout.write("Upgraded 1 package\n")
    else:
        process.stdout.write(SERVER_OUTPUT.get(command, ""))
    process.exit(0)


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return False


@pytest.fixture
async def ssh_server() -> AsyncIterator[tuple[asyncssh.SSHAcceptor, str]]:
    commands_run.clear()
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    server = await asyncssh.listen(
        "127.0.0.1", 0, server_factory=_Server, server_host_keys=[host_key], process_factory=_handle
    )
    yield server, hostkey.key_line(host_key)
    server.close()
    await server.wait_closed()


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with dbs.credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


async def _add_ssh_integration(
    dbs, port: int, host_key: str | None, extra_config: dict | None = None
) -> int:
    key = asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()
    async with dbs.credentials_session_factory() as session:
        credential = await CredentialService(get_secret_box()).create(
            session,
            "ssh",
            CredentialType.SSH_KEY,
            {"username": "banana", "private_key": key, "passphrase": SECRET},
        )
    async with dbs.app_session_factory() as session:
        site = await ensure_default_site(session)
        device = Device(
            site_id=site.id, display_name="lab", primary_ip="127.0.0.1", device_type=DeviceType.LINUX
        )
        session.add(device)
        await session.flush()
        config = {"device_id": device.id, "host": "127.0.0.1", "port": port, "timeout_seconds": 5.0}
        if host_key:
            config["host_key"] = host_key
        config.update(extra_config or {})
        integration = Integration(
            integration_type="generic_ssh", name="lab ssh", config=config, credential_id=credential.id
        )
        session.add(integration)
        await session.commit()
        return integration.id


async def _add_ssh_integration_password(dbs, port: int, host_key: str | None) -> int:
    async with dbs.credentials_session_factory() as session:
        credential = await CredentialService(get_secret_box()).create(
            session, "ssh-password", CredentialType.SSH_PASSWORD, {"username": "banana", "password": SECRET}
        )
    async with dbs.app_session_factory() as session:
        site = await ensure_default_site(session)
        device = Device(
            site_id=site.id, display_name="lab", primary_ip="127.0.0.1", device_type=DeviceType.LINUX
        )
        session.add(device)
        await session.flush()
        config = {"device_id": device.id, "host": "127.0.0.1", "port": port, "timeout_seconds": 5.0}
        if host_key:
            config["host_key"] = host_key
        integration = Integration(
            integration_type="generic_ssh",
            name="lab ssh password",
            config=config,
            credential_id=credential.id,
        )
        session.add(integration)
        await session.commit()
        return integration.id


async def _add_ssh_integration_windows(dbs, port: int, host_key: str | None) -> int:
    key = asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()
    async with dbs.credentials_session_factory() as session:
        credential = await CredentialService(get_secret_box()).create(
            session, "ssh-win", CredentialType.SSH_KEY, {"username": "banana", "private_key": key}
        )
    async with dbs.app_session_factory() as session:
        site = await ensure_default_site(session)
        device = Device(
            site_id=site.id, display_name="winhost", primary_ip="127.0.0.1", device_type=DeviceType.OTHER
        )
        session.add(device)
        await session.flush()
        config: dict[str, object] = {
            "device_id": device.id,
            "host": "127.0.0.1",
            "port": port,
            "timeout_seconds": 5.0,
            "os_family": "windows",
        }
        if host_key:
            config["host_key"] = host_key
        integration = Integration(
            integration_type="generic_ssh", name="win ssh", config=config, credential_id=credential.id
        )
        session.add(integration)
        await session.commit()
        return integration.id


async def test_ssh_readonly_runs_an_allowed_command_with_a_password_credential(databases, ssh_server):
    """A generic_ssh integration created with a password credential (no private_key at all) must work
    end-to-end through the agent's own ssh_readonly tool, the same as a key-based one - this is the exact
    path that silently failed with "Invalid SSH key: 'private_key'" before SshCredential/ssh_auth_kwargs."""
    server, key = ssh_server
    integration_id = await _add_ssh_integration_password(databases, server.get_port(), key)

    result = await agent_tools.dispatch(
        databases,
        "ssh_readonly",
        {"integration_id": integration_id, "command": "uname -a"},
        enabled=["ssh_readonly"],
    )

    assert result["stdout"] == "Linux lab 6.1.0\n" and result["exit_status"] == 0
    assert SECRET not in json.dumps(result)


async def test_list_targets_has_no_secrets(databases, ssh_server):
    server, key = ssh_server
    integration_id = await _add_ssh_integration(databases, server.get_port(), key)
    async with databases.app_session_factory() as session:
        session.add(Service(name="web", service_type=ServiceType.HTTP, config={"url": "http://x/"}))
        await session.commit()

    result = await agent_tools.dispatch(
        databases, "list_inspect_targets", {}, enabled=["list_inspect_targets"]
    )

    assert result["integrations"] == [
        {
            "integration_id": integration_id,
            "name": "lab ssh",
            "type": "generic_ssh",
            "os_kind": "linux",
            "device": "lab",
            "ip": "127.0.0.1",
        }
    ]
    assert result["web_services"][0]["url"] == "http://x/"
    assert SECRET not in json.dumps(result) and key not in json.dumps(result)


async def test_list_targets_skips_an_integration_with_no_host(databases, ssh_server):
    server, key = ssh_server
    usable = await _add_ssh_integration(databases, server.get_port(), key)
    async with databases.app_session_factory() as session:
        session.add(Integration(integration_type="generic_ssh", name="blank", config={}, credential_id=1))
        await session.commit()

    result = await agent_tools.dispatch(
        databases, "list_inspect_targets", {}, enabled=["list_inspect_targets"]
    )

    assert [t["integration_id"] for t in result["integrations"]] == [usable]


async def test_ssh_readonly_runs_an_allowed_command(databases, ssh_server):
    server, key = ssh_server
    integration_id = await _add_ssh_integration(databases, server.get_port(), key)

    result = await agent_tools.dispatch(
        databases,
        "ssh_readonly",
        {"integration_id": integration_id, "command": "uname -a"},
        enabled=["ssh_readonly"],
    )

    assert result["stdout"] == "Linux lab 6.1.0\n" and result["exit_status"] == 0
    assert commands_run == ["uname -a"]
    assert SECRET not in json.dumps(result)


async def test_ssh_readonly_wraps_a_windows_host_in_powershell_with_an_escaped_pipe(databases, ssh_server):
    """A generic_ssh integration whose learned os_family is "windows" routes through check_windows's
    cmdlet allowlist (reused from winrm_readonly) and is wrapped for cmd.exe, Win32-OpenSSH's default
    remote shell - the pipe into Out-String must be caret-escaped so cmd.exe passes it through to
    powershell.exe instead of treating it as its own pipe."""
    server, key = ssh_server
    integration_id = await _add_ssh_integration_windows(databases, server.get_port(), key)

    result = await agent_tools.dispatch(
        databases,
        "ssh_readonly",
        {"integration_id": integration_id, "command": "Get-Process"},
        enabled=["ssh_readonly"],
    )

    assert commands_run == [
        "powershell -NoProfile -NonInteractive -Command Get-Process ^| Out-String -Width 200"
    ]
    assert result["command"] == "Get-Process"


async def test_ssh_readonly_applies_the_windows_cmdlet_allowlist_for_a_windows_host(databases, ssh_server):
    server, key = ssh_server
    integration_id = await _add_ssh_integration_windows(databases, server.get_port(), key)

    with pytest.raises(agent_tools.AgentToolError):
        await agent_tools.dispatch(
            databases,
            "ssh_readonly",
            {"integration_id": integration_id, "command": "Remove-Item C:\\Windows"},
            enabled=["ssh_readonly"],
        )
    assert commands_run == []  # refused before connecting, same guarantee as the Linux allowlist


async def test_list_targets_reports_a_detected_windows_host(databases, ssh_server):
    server, key = ssh_server
    integration_id = await _add_ssh_integration_windows(databases, server.get_port(), key)

    result = await agent_tools.dispatch(
        databases, "list_inspect_targets", {}, enabled=["list_inspect_targets"]
    )

    by_id = {t["integration_id"]: t for t in result["integrations"]}
    assert by_id[integration_id]["os_kind"] == "windows"


@pytest.mark.parametrize("command", ["uname -a; id", "cat /etc/shadow", "rm -rf /", "apt-get upgrade"])
async def test_ssh_readonly_refuses_before_connecting(databases, ssh_server, command):
    server, key = ssh_server
    integration_id = await _add_ssh_integration(databases, server.get_port(), key)

    with pytest.raises(agent_tools.AgentToolError):
        await agent_tools.dispatch(
            databases,
            "ssh_readonly",
            {"integration_id": integration_id, "command": command},
            enabled=["ssh_readonly"],
        )
    assert commands_run == []


async def test_ssh_readonly_needs_a_pinned_host_key(databases, ssh_server):
    server, _ = ssh_server
    integration_id = await _add_ssh_integration(databases, server.get_port(), None)

    with pytest.raises(agent_tools.AgentToolError, match="not pinned"):
        await agent_tools.dispatch(
            databases,
            "ssh_readonly",
            {"integration_id": integration_id, "command": "uname -a"},
            enabled=["ssh_readonly"],
        )
    assert commands_run == []


async def test_ssh_readonly_refuses_a_changed_host_key_when_auto_repin_is_off(databases, ssh_server):
    server, _ = ssh_server
    other = hostkey.key_line(asyncssh.generate_private_key("ssh-ed25519"))
    integration_id = await _add_ssh_integration(
        databases, server.get_port(), other, extra_config={"auto_repin_host_key": False}
    )

    with pytest.raises(agent_tools.AgentToolError, match="does not match"):
        await agent_tools.dispatch(
            databases,
            "ssh_readonly",
            {"integration_id": integration_id, "command": "uname -a"},
            enabled=["ssh_readonly"],
        )


async def test_ssh_readonly_retries_with_the_real_key_by_default(databases, ssh_server):
    server, _ = ssh_server
    stale = hostkey.key_line(asyncssh.generate_private_key("ssh-ed25519"))
    integration_id = await _add_ssh_integration(databases, server.get_port(), stale)

    result = await agent_tools.dispatch(
        databases,
        "ssh_readonly",
        {"integration_id": integration_id, "command": "uname -a"},
        enabled=["ssh_readonly"],
    )
    assert result["exit_status"] == 0
    assert "Linux lab" in result["stdout"]


async def test_wrong_integration_type_is_refused(databases, ssh_server):
    server, key = ssh_server
    integration_id = await _add_ssh_integration(databases, server.get_port(), key)

    with pytest.raises(agent_tools.AgentToolError, match="not windows_winrm"):
        await agent_tools.dispatch(
            databases,
            "winrm_readonly",
            {"integration_id": integration_id, "command": "Get-Process"},
            enabled=["winrm_readonly"],
        )


async def test_winrm_readonly_policy_and_suffix(databases, monkeypatch):
    async with databases.credentials_session_factory() as session:
        credential = await CredentialService(get_secret_box()).create(
            session, "win", CredentialType.BASIC_AUTH, {"username": "u", "password": SECRET}
        )
    async with databases.app_session_factory() as session:
        integration = Integration(
            integration_type="windows_winrm",
            name="win",
            config={"device_id": 1, "host": "10.0.0.9"},
            credential_id=credential.id,
        )
        session.add(integration)
        await session.commit()
    scripts: list[str] = []

    async def fake(config, credential, script):
        scripts.append(script)
        return 0, "ok", ""

    monkeypatch.setattr("app.llm.inspect_tools.run_powershell", fake)
    args = {"integration_id": integration.id, "command": "Get-Service -Name Spooler"}
    result = await agent_tools.dispatch(databases, "winrm_readonly", args, enabled=["winrm_readonly"])

    assert result["stdout"] == "ok"
    assert scripts == ["Get-Service -Name Spooler | Out-String -Width 200"]
    with pytest.raises(agent_tools.AgentToolError):
        await agent_tools.dispatch(
            databases,
            "winrm_readonly",
            {**args, "command": "Get-Service | Stop-Service"},
            enabled=["winrm_readonly"],
        )


async def test_proxmox_get_allows_only_read_paths(databases, monkeypatch):
    async with databases.credentials_session_factory() as session:
        credential = await CredentialService(get_secret_box()).create(
            session, "pve", CredentialType.API_TOKEN, {"token_secret": SECRET}
        )
    async with databases.app_session_factory() as session:
        integration = Integration(
            integration_type="proxmox",
            name="pve",
            config={"host": "10.0.0.2", "token_id": "a@pve!t"},
            credential_id=credential.id,
        )
        session.add(integration)
        await session.commit()
    seen: list[str] = []

    async def fake_get(self, path):
        seen.append(path)
        return {"uptime": 5}

    monkeypatch.setattr("app.integrations.proxmox.client.ProxmoxClient.get", fake_get)
    ok = await agent_tools.dispatch(
        databases,
        "proxmox_get",
        {"integration_id": integration.id, "path": "/nodes/pve1/status"},
        enabled=["proxmox_get"],
    )
    assert json.loads(ok["data"]) == {"uptime": 5} and seen == ["/nodes/pve1/status"]
    with pytest.raises(agent_tools.AgentToolError):
        await agent_tools.dispatch(
            databases,
            "proxmox_get",
            {"integration_id": integration.id, "path": "/access/users"},
            enabled=["proxmox_get"],
        )
    assert seen == ["/nodes/pve1/status"]


async def test_apply_updates_is_dry_run_safe_and_audited(databases, ssh_server):
    server, key = ssh_server
    integration_id = await _add_ssh_integration(databases, server.get_port(), key)
    args = {"integration_id": integration_id}

    dry = await agent_tools.dispatch(
        databases, "apply_updates", args, enabled=["apply_updates"], dry_run=True
    )
    assert dry["dry_run"] is True and commands_run == []

    result = await agent_tools.dispatch(databases, "apply_updates", args, enabled=["apply_updates"])
    assert result["package_manager"] == "apt" and "Upgraded 1 package" in result["stdout_tail"]
    assert commands_run[-1].startswith("sudo -n apt-get -y")
    async with databases.app_session_factory() as session:
        events = list(await session.scalars(select(Event).where(Event.category == "ai_change")))
    assert len(events) == 1 and "lab ssh" in events[0].message


async def test_http_inspect_tells_the_agent_not_to_retry_an_unreachable_service(databases):
    async with databases.app_session_factory() as session:
        service = Service(name="web", service_type=ServiceType.HTTP, config={"url": "http://127.0.0.1:9/"})
        session.add(service)
        await session.commit()
        service_id = service.id

    with pytest.raises(agent_tools.AgentToolError, match=r"http://127\.0\.0\.1:9/.*do not retry"):
        await agent_tools.dispatch(
            databases, "http_inspect", {"service_id": service_id}, enabled=["http_inspect"]
        )
