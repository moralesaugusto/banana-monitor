from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import asyncssh
import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_databases
from app.discovery.auto_login import attempt_ssh_auto_login, attempt_wallet_login
from app.domain.enums import DeviceType
from app.domain.models import Device, Integration


class _NoAuthServer(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return False  # test server accepts any client without checking credentials


@pytest.fixture
async def ssh_test_server() -> AsyncIterator[asyncssh.SSHAcceptor]:
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    server = await asyncssh.listen("127.0.0.1", 0, server_factory=_NoAuthServer, server_host_keys=[host_key])
    yield server
    server.close()
    await server.wait_closed()


async def _setup_network_with_credential(
    client: AsyncClient, secret: dict[str, str], credential_type: str = "ssh_key"
) -> tuple[int, int]:
    network = (await client.post("/api/networks", json={"name": "LAN", "cidr": "127.0.0.0/30"})).json()
    credential = (
        await client.post(
            "/api/credentials",
            json={"label": "auto-login", "credential_type": credential_type, "secret": secret},
        )
    ).json()
    await client.post(
        f"/api/networks/{network['id']}/credentials",
        json={"credential_id": credential["id"], "priority": 0},
    )
    return network["id"], credential["id"]


def _ssh_secret() -> dict[str, str]:
    key = asyncssh.generate_private_key("ssh-ed25519")
    return {"username": "banana", "private_key": key.export_private_key().decode()}


async def _approval(databases, required: bool) -> None:  # noqa: ANN001
    from app.domain.bootstrap import ensure_default_discovery_settings

    async with databases.app_session_factory() as session:
        (await ensure_default_discovery_settings(session)).ssh_hostkey_approval = required
        await session.commit()


async def _auto_repin(databases, enabled: bool) -> None:  # noqa: ANN001
    from app.domain.bootstrap import ensure_default_discovery_settings

    async with databases.app_session_factory() as session:
        (await ensure_default_discovery_settings(session)).ssh_hostkey_auto_repin = enabled
        await session.commit()


async def _unmanaged_device(databases, network_id: int) -> int:  # noqa: ANN001
    async with databases.app_session_factory() as session:
        device = Device(
            site_id=1,
            network_id=network_id,
            display_name="test-host",
            primary_ip="127.0.0.1",
            device_type=DeviceType.OTHER,
            managed=False,
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return device.id


@pytest.mark.asyncio
async def test_successful_login_provisions_integration_and_promotes_device(
    client: AsyncClient, ssh_test_server: asyncssh.SSHAcceptor
) -> None:
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    network_id, credential_id = await _setup_network_with_credential(
        client,
        {"username": "banana", "private_key": client_key.export_private_key().decode()},
    )

    databases = get_databases()
    await _approval(databases, False)  # the behaviour of an install that predates host-key approval
    device_id = await _unmanaged_device(databases, network_id)

    await attempt_ssh_auto_login(
        databases, network_id, "127.0.0.1", device_id, port=ssh_test_server.get_port()
    )

    async with databases.app_session_factory() as session:
        refreshed = await session.get(Device, device_id)
        assert refreshed.managed is True
        assert refreshed.device_type == DeviceType.LINUX

        result = await session.execute(
            select(Integration).where(Integration.integration_type == "generic_ssh")
        )
        integrations = list(result.scalars().all())
        assert len(integrations) == 1
        assert integrations[0].credential_id == credential_id
        assert integrations[0].config["host_key"].startswith("ssh-ed25519 ")  # pinned for later polls


@pytest.mark.asyncio
async def test_failed_login_leaves_device_unmanaged(client: AsyncClient) -> None:
    """No SSH server is listening on this port, so the connection should fail
    closed without crashing the scan or provisioning anything."""
    network_id, _ = await _setup_network_with_credential(
        client, {"username": "banana", "password": "wrong"}, credential_type="ssh_password"
    )

    databases = get_databases()
    async with databases.app_session_factory() as session:
        device = Device(
            site_id=1,
            network_id=network_id,
            display_name="test-host",
            primary_ip="127.0.0.1",
            device_type=DeviceType.OTHER,
            managed=False,
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        device_id = device.id

    await attempt_ssh_auto_login(databases, network_id, "127.0.0.1", device_id, port=1)

    async with databases.app_session_factory() as session:
        refreshed = await session.get(Device, device_id)
        assert refreshed.managed is False


@pytest.mark.asyncio
async def test_already_managed_device_is_not_retried(client: AsyncClient) -> None:
    """Guards against re-spraying credentials at an already-provisioned
    device on every later scan cycle."""
    network_id, _ = await _setup_network_with_credential(client, {"username": "x", "password": "y"})

    databases = get_databases()
    async with databases.app_session_factory() as session:
        device = Device(
            site_id=1,
            network_id=network_id,
            display_name="already-managed",
            primary_ip="127.0.0.1",
            device_type=DeviceType.LINUX,
            managed=True,
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        device_id = device.id

    # port=1 (nothing listening) would fail anyway, but the point is this
    # returns immediately without even querying the credential bindings.
    await attempt_ssh_auto_login(databases, network_id, "127.0.0.1", device_id, port=1)

    async with databases.app_session_factory() as session:
        result = await session.execute(select(Integration))
        assert list(result.scalars().all()) == []


@pytest.mark.asyncio
async def test_no_credential_bindings_is_a_noop(client: AsyncClient) -> None:
    network = (await client.post("/api/networks", json={"name": "LAN", "cidr": "127.0.0.0/30"})).json()
    databases = get_databases()
    async with databases.app_session_factory() as session:
        device = Device(
            site_id=1,
            network_id=network["id"],
            display_name="test-host",
            primary_ip="127.0.0.1",
            device_type=DeviceType.OTHER,
            managed=False,
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        device_id = device.id

    await attempt_ssh_auto_login(databases, network["id"], "127.0.0.1", device_id, port=1)

    async with databases.app_session_factory() as session:
        refreshed = await session.get(Device, device_id)
        assert refreshed.managed is False


@pytest.mark.asyncio
async def test_no_credential_is_sent_until_the_host_key_is_approved(
    client: AsyncClient, ssh_test_server: asyncssh.SSHAcceptor
) -> None:
    key = asyncssh.generate_private_key("ssh-ed25519")
    network_id, _ = await _setup_network_with_credential(
        client, {"username": "banana", "private_key": key.export_private_key().decode()}
    )
    databases = get_databases()
    device_id = await _unmanaged_device(databases, network_id)
    port = ssh_test_server.get_port()

    with patch("app.discovery.auto_login._try_ssh_login", AsyncMock(return_value=True)) as login:
        await attempt_ssh_auto_login(databases, network_id, "127.0.0.1", device_id, port=port)
        login.assert_not_called()  # a new host with approval required: nothing is tried

        pending = (await client.get("/api/ssh-host-keys")).json()
        assert len(pending) == 1 and pending[0]["approved"] is False
        assert pending[0]["fingerprint"].startswith("SHA256:")
        events = (await client.get("/api/events")).json()
        assert any("awaits approval" in e["message"] for e in events)
        assert (await client.get("/api/integrations")).json() == []

        approved = await client.post(f"/api/ssh-host-keys/{pending[0]['id']}/approve")
        assert approved.json()["approved"] is True
        await attempt_ssh_auto_login(databases, network_id, "127.0.0.1", device_id, port=port)
        login.assert_called_once()

    integrations = (await client.get("/api/integrations")).json()
    assert len(integrations) == 1 and integrations[0]["config"]["host_key"].startswith("ssh-ed25519 ")


@pytest.mark.asyncio
async def test_a_changed_host_key_is_repinned_automatically_by_default(
    client: AsyncClient, ssh_test_server: asyncssh.SSHAcceptor
) -> None:
    from app.domain.models import SshHostKey

    network_id, _ = await _setup_network_with_credential(client, _ssh_secret())
    databases = get_databases()
    device_id = await _unmanaged_device(databases, network_id)
    port = ssh_test_server.get_port()
    other = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode().strip()
    async with databases.app_session_factory() as session:
        session.add(SshHostKey(host="127.0.0.1", port=port, public_key=other, fingerprint="x", approved=True))
        await session.commit()

    with patch("app.discovery.auto_login._try_ssh_login", AsyncMock(return_value=True)) as login:
        await attempt_ssh_auto_login(databases, network_id, "127.0.0.1", device_id, port=port)
        login.assert_called_once()  # re-pinned automatically (ssh_hostkey_auto_repin defaults on)

    row = (await client.get("/api/ssh-host-keys")).json()[0]
    assert row["approved"] is True and row["changed"] is False
    assert any("re-pinned automatically" in e["message"] for e in (await client.get("/api/events")).json())


@pytest.mark.asyncio
async def test_a_changed_host_key_pauses_auto_login_when_auto_repin_is_turned_off(
    client: AsyncClient, ssh_test_server: asyncssh.SSHAcceptor
) -> None:
    from app.domain.models import SshHostKey

    network_id, _ = await _setup_network_with_credential(client, _ssh_secret())
    databases = get_databases()
    await _auto_repin(databases, False)
    device_id = await _unmanaged_device(databases, network_id)
    port = ssh_test_server.get_port()
    other = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode().strip()
    async with databases.app_session_factory() as session:
        session.add(SshHostKey(host="127.0.0.1", port=port, public_key=other, fingerprint="x", approved=True))
        await session.commit()

    with patch("app.discovery.auto_login._try_ssh_login", AsyncMock(return_value=True)) as login:
        await attempt_ssh_auto_login(databases, network_id, "127.0.0.1", device_id, port=port)
        login.assert_not_called()

    row = (await client.get("/api/ssh-host-keys")).json()[0]
    assert row["approved"] is False and row["changed"] is True
    assert any("changed" in e["message"] for e in (await client.get("/api/events")).json())


@pytest.mark.asyncio
async def test_without_the_approval_setting_the_first_key_is_pinned_and_a_different_one_is_refused(
    client: AsyncClient, ssh_test_server: asyncssh.SSHAcceptor
) -> None:
    network_id, _ = await _setup_network_with_credential(client, _ssh_secret())
    databases = get_databases()
    await _approval(databases, False)
    device_id = await _unmanaged_device(databases, network_id)
    port = ssh_test_server.get_port()

    with patch("app.discovery.auto_login._try_ssh_login", AsyncMock(return_value=False)) as login:
        await attempt_ssh_auto_login(databases, network_id, "127.0.0.1", device_id, port=port)
        assert login.call_count == 1
    assert (await client.get("/api/ssh-host-keys")).json()[0]["approved"] is True


@pytest.mark.asyncio
async def test_ssh_wallet_credential_is_tried_after_network_bindings_are_exhausted(
    client: AsyncClient,
) -> None:
    """A credential saved with no host (the wallet - see docs/credentials.md) is tried on an SSH-open
    host too, after any credential bound to that host's network has been tried and failed."""
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    accepted_public_key = client_key.export_public_key("openssh").decode().strip()

    class _OnlyOneKeyServer(asyncssh.SSHServer):
        def begin_auth(self, username: str) -> bool:
            return True  # authentication is required (unlike _NoAuthServer)

        def public_key_auth_supported(self) -> bool:
            return True

        def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
            return key.export_public_key("openssh").decode().strip() == accepted_public_key

        def password_auth_supported(self) -> bool:
            return False

    host_key = asyncssh.generate_private_key("ssh-ed25519")
    server = await asyncssh.listen(
        "127.0.0.1", 0, server_factory=_OnlyOneKeyServer, server_host_keys=[host_key]
    )
    try:
        network_id, _ = await _setup_network_with_credential(
            client, {"username": "banana", "password": "wrong-this-is-a-key-only-server"}, "ssh_password"
        )
        wallet_credential = (
            await client.post(
                "/api/credentials",
                json={
                    "label": "ssh-wallet",
                    "credential_type": "ssh_key",
                    "secret": {"username": "banana", "private_key": client_key.export_private_key().decode()},
                },
            )
        ).json()
        await client.post(
            "/api/integrations",
            json={
                "integration_type": "generic_ssh",
                "name": "ssh-wallet",
                "config": {},
                "credential_id": wallet_credential["id"],
            },
        )

        databases = get_databases()
        await _approval(databases, False)
        device_id = await _unmanaged_device(databases, network_id)

        await attempt_ssh_auto_login(databases, network_id, "127.0.0.1", device_id, port=server.get_port())
    finally:
        server.close()
        await server.wait_closed()

    async with databases.app_session_factory() as session:
        refreshed = await session.get(Device, device_id)
        assert refreshed.managed is True
        result = await session.execute(
            select(Integration).where(Integration.integration_type == "generic_ssh")
        )
        provisioned = [i for i in result.scalars().all() if i.config.get("host")]
        assert len(provisioned) == 1
        assert provisioned[0].credential_id == wallet_credential["id"]


@pytest.mark.asyncio
@respx.mock
async def test_wallet_credential_is_tried_against_a_non_ssh_host_and_provisions_an_integration(
    client: AsyncClient,
) -> None:
    """The generalized (non-SSH) half of the credential wallet - see attempt_wallet_login's docstring."""
    respx.get("http://192.168.1.50:3000/control/status").mock(
        return_value=httpx.Response(200, json={"protection_enabled": True})
    )
    credential = (
        await client.post(
            "/api/credentials",
            json={
                "label": "adguard-wallet",
                "credential_type": "basic_auth",
                "secret": {"username": "admin", "password": "sUpErSeCrEt"},
            },
        )
    ).json()
    await client.post(
        "/api/integrations",
        json={
            "integration_type": "adguard_home",
            "name": "adguard-wallet",
            "config": {},
            "credential_id": credential["id"],
        },
    )

    databases = get_databases()
    async with databases.app_session_factory() as session:
        device = Device(
            site_id=1,
            display_name="agh",
            primary_ip="192.168.1.50",
            device_type=DeviceType.OTHER,
            managed=False,
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        device_id = device.id

    await attempt_wallet_login(databases, "192.168.1.50", device_id, 3000, "adguard_home")

    async with databases.app_session_factory() as session:
        refreshed = await session.get(Device, device_id)
        assert refreshed.managed is True
        result = await session.execute(
            select(Integration).where(Integration.integration_type == "adguard_home")
        )
        provisioned = [i for i in result.scalars().all() if i.config.get("host")]
        assert len(provisioned) == 1
        assert provisioned[0].credential_id == credential["id"]
        assert provisioned[0].config["host"] == "192.168.1.50"


@pytest.mark.asyncio
async def test_wallet_login_is_not_retried_against_an_already_managed_device(client: AsyncClient) -> None:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        device = Device(
            site_id=1,
            display_name="already-managed",
            primary_ip="192.168.1.60",
            device_type=DeviceType.OTHER,
            managed=True,
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        device_id = device.id

    await attempt_wallet_login(databases, "192.168.1.60", device_id, 3000, "adguard_home")

    async with databases.app_session_factory() as session:
        result = await session.execute(
            select(Integration).where(Integration.integration_type == "adguard_home")
        )
        assert list(result.scalars().all()) == []
