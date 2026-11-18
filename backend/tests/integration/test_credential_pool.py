import json
from collections.abc import AsyncIterator

import asyncssh
import pytest
from sqlalchemy import select

from app.credentials.crypto import get_secret_box
from app.credentials.models import CredentialsBase
from app.credentials.service import CredentialService
from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_ai_mode_settings, ensure_default_site
from app.domain.enums import CredentialType, DeviceType
from app.domain.models import AiAgent, Device, Event, Integration, SshHostKey
from app.domain.models import Base as AppBase
from app.integrations.generic_ssh import hostkey
from app.llm import agent_tools, credential_pool
from app.llm.tool_base import AgentToolError

GOOD = "the-good-password"
BAD = "a-wrong-password"
attempts: list[str] = []


async def _handle(process: asyncssh.SSHServerProcess) -> None:
    process.stdout.write("Linux lab\n")
    process.exit(0)


class _PasswordServer(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        attempts.append(password)
        return password == GOOD


@pytest.fixture
async def ssh_server() -> AsyncIterator[tuple[int, str]]:
    attempts.clear()
    key = asyncssh.generate_private_key("ssh-ed25519")
    server = await asyncssh.listen(
        "127.0.0.1", 0, server_factory=_PasswordServer, server_host_keys=[key], process_factory=_handle
    )
    yield server.sockets[0].getsockname()[1], hostkey.key_line(key)
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


async def _credential(dbs, label: str, password: str, *, pool: bool = True) -> int:
    async with dbs.credentials_session_factory() as session:
        credential = await CredentialService(get_secret_box()).create(
            session,
            label,
            CredentialType.SSH_PASSWORD,
            {"username": "banana", "password": password},
            in_agent_pool=pool,
        )
        return credential.id


async def _agent(dbs, scope: str = "pool", ids: list[int] | None = None) -> None:
    async with dbs.app_session_factory() as session:
        session.add(AiAgent(name="bellaco", credential_scope=scope, credential_scope_ids=ids or []))
        await session.commit()


async def _approve_key(dbs, port: int, line: str) -> None:
    async with dbs.app_session_factory() as session:
        session.add(
            SshHostKey(
                host="127.0.0.1",
                port=port,
                public_key=line,
                fingerprint=hostkey.fingerprint(line),
                approved=True,
            )
        )
        await session.commit()


async def _set_flags(dbs, **flags: bool) -> None:
    async with dbs.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        for name, value in flags.items():
            setattr(settings, name, value)
        await session.commit()


async def _call(dbs, port: int, name: str = "ssh_readonly", **extra):
    arguments = {"host": "127.0.0.1", "port": port, "command": "uname -a", **extra}
    return await agent_tools.dispatch(dbs, name, arguments, agent_name="bellaco")


async def test_pool_tries_credentials_until_one_is_accepted(databases, ssh_server) -> None:
    port, line = ssh_server
    await _credential(databases, "wrong", BAD)
    await _credential(databases, "right", GOOD)
    await _agent(databases)
    await _approve_key(databases, port, line)

    result = await _call(databases, port)

    assert result["stdout"].startswith("Linux")
    assert result["credential_used"] == {"label": "right", "source": "pool"}
    assert attempts[:2] == [BAD, GOOD]
    assert GOOD not in json.dumps(result)
    async with databases.app_session_factory() as session:
        events = (await session.scalars(select(Event).where(Event.category == "ai_credential_use"))).all()
    assert len(events) == 1 and "right" in events[0].message and GOOD not in events[0].message


async def test_a_host_bound_integration_wins_over_the_pool(databases, ssh_server) -> None:
    port, line = ssh_server
    bound = await _credential(databases, "bound-one", GOOD, pool=False)
    await _credential(databases, "pool-one", GOOD)
    await _agent(databases)
    async with databases.app_session_factory() as session:
        site = await ensure_default_site(session)
        device = Device(
            site_id=site.id, display_name="lab", primary_ip="127.0.0.1", device_type=DeviceType.LINUX
        )
        session.add(device)
        await session.flush()
        session.add(
            Integration(
                integration_type="generic_ssh",
                name="lab ssh",
                config={"device_id": device.id, "host": "127.0.0.1", "port": port, "host_key": line},
                credential_id=bound,
            )
        )
        await session.commit()

    result = await _call(databases, port)

    assert result["credential_used"] == {"label": "bound-one", "source": "host-bound"}


async def test_host_bound_only_agents_do_not_use_the_pool(databases, ssh_server) -> None:
    port, line = ssh_server
    await _credential(databases, "pool-one", GOOD)
    await _agent(databases, scope="bound")
    await _approve_key(databases, port, line)

    with pytest.raises(AgentToolError, match="no stored credential may be used"):
        await _call(databases, port)
    assert attempts == []


async def test_selected_agents_only_use_the_ticked_credentials(databases, ssh_server) -> None:
    port, line = ssh_server
    await _credential(databases, "not-ticked", GOOD)
    ticked = await _credential(databases, "ticked", GOOD, pool=False)
    await _agent(databases, scope="selected", ids=[ticked])
    await _approve_key(databases, port, line)

    result = await _call(databases, port)

    assert result["credential_used"]["label"] == "ticked"


async def test_an_unapproved_ssh_host_key_stops_before_any_password_is_sent(databases, ssh_server) -> None:
    port, _ = ssh_server
    await _credential(databases, "right", GOOD)
    await _agent(databases)

    with pytest.raises(AgentToolError, match="not approved"):
        await _call(databases, port)
    assert attempts == []


async def test_relaxing_the_host_key_safeguard_trusts_an_unseen_key_and_says_so(
    databases, ssh_server
) -> None:
    port, _ = ssh_server
    await _credential(databases, "right", GOOD)
    await _agent(databases)
    await _set_flags(databases, cred_trust_new_host_keys=True)

    result = await _call(databases, port)

    assert result["credential_used"]["label"] == "right"
    assert result["safeguards_relaxed"] == ["an unseen SSH host key is trusted on first use"]


async def test_attempts_are_capped_per_host_unless_the_safeguard_is_relaxed(
    databases, ssh_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    port, line = ssh_server
    monkeypatch.setattr(credential_pool, "MAX_ATTEMPTS_PER_HOST", 2)
    for index in range(3):
        await _credential(databases, f"bad-{index}", BAD)
    await _credential(databases, "right", GOOD)
    await _agent(databases)
    await _approve_key(databases, port, line)

    with pytest.raises(AgentToolError, match="stopped to avoid locking an account"):
        await _call(databases, port)
    assert attempts == [BAD, BAD]

    await _set_flags(databases, cred_no_attempt_limit=True)
    credential_pool.clear_memory()
    result = await _call(databases, port)
    assert result["credential_used"]["label"] == "right"


async def test_apply_updates_does_not_use_pool_credentials_by_default(databases, ssh_server) -> None:
    port, line = ssh_server
    await _credential(databases, "right", GOOD)
    await _agent(databases)
    await _approve_key(databases, port, line)

    with pytest.raises(AgentToolError, match="no stored credential may be used"):
        await agent_tools.dispatch(
            databases, "apply_updates", {"host": "127.0.0.1", "port": port}, agent_name="bellaco"
        )
    assert attempts == []


async def test_a_host_outside_the_inventory_needs_the_safeguard_relaxed(databases) -> None:
    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
    with pytest.raises(AgentToolError, match="not a known device"):
        await credential_pool._check_scope(databases, "10.9.9.9", None, settings)

    settings.cred_allow_unlisted_hosts = True
    assert await credential_pool._check_scope(databases, "10.9.9.9", None, settings) == (None, False)

    with pytest.raises(AgentToolError, match="public address"):
        await credential_pool._check_scope(databases, "8.8.8.8", None, settings)


async def test_list_inspect_targets_names_pool_credentials_but_never_secrets(databases) -> None:
    await _credential(databases, "in-pool", GOOD)
    await _credential(databases, "not-in-pool", GOOD, pool=False)
    await _agent(databases)

    result = await agent_tools.dispatch(databases, "list_inspect_targets", {}, agent_name="bellaco")

    assert result["credential_pool"] == {
        "scope": "pool",
        "credentials": [{"label": "in-pool", "credential_type": "ssh_password"}],
    }
    assert GOOD not in json.dumps(result)
