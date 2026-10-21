from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from app.integrations.base import TargetDescriptor
from app.integrations.proxmox.plugin import ProxmoxPlugin

BASE_URL = "https://pve.local:8006/api2/json"

CONFIG = {"host": "pve.local", "port": 8006, "token_id": "banana@pve!token1"}
CREDENTIAL = {"token_secret": "sekrit-value"}

NODES = [{"node": "pve1", "status": "online"}]
QEMU = [
    {
        "vmid": 100,
        "name": "vm1",
        "status": "running",
        "cpu": 0.1,
        "mem": 500_000_000,
        "maxmem": 1_000_000_000,
        "uptime": 3600,
    }
]
LXC = [
    {
        "vmid": 200,
        "name": "ct1",
        "status": "stopped",
        "cpu": 0.0,
        "mem": 0,
        "maxmem": 512_000_000,
        "uptime": 0,
    }
]
NODE_STATUS = {"cpu": 0.05, "memory": {"total": 1_000_000_000, "used": 300_000_000}}


def _mock_inventory(router: respx.MockRouter) -> None:
    router.get(f"{BASE_URL}/nodes").mock(return_value=httpx.Response(200, json={"data": NODES}))
    router.get(f"{BASE_URL}/nodes/pve1/qemu").mock(return_value=httpx.Response(200, json={"data": QEMU}))
    router.get(f"{BASE_URL}/nodes/pve1/lxc").mock(return_value=httpx.Response(200, json={"data": LXC}))


@pytest.mark.asyncio
@respx.mock
async def test_list_targets_discovers_nodes_vms_lxcs() -> None:
    _mock_inventory(respx)
    plugin = ProxmoxPlugin()

    targets = await plugin.list_targets(CONFIG, CREDENTIAL)

    refs = {t.external_ref: t for t in targets}
    assert set(refs) == {"node:pve1", "qemu:pve1:100", "lxc:pve1:200"}
    assert refs["node:pve1"].attributes["device_type"] == "proxmox_node"
    assert refs["qemu:pve1:100"].attributes["device_type"] == "proxmox_vm"
    assert refs["lxc:pve1:200"].attributes["device_type"] == "proxmox_lxc"
    assert refs["qemu:pve1:100"].display_name == "vm1"


@pytest.mark.asyncio
@respx.mock
async def test_list_targets_without_credential_returns_empty() -> None:
    plugin = ProxmoxPlugin()
    assert await plugin.list_targets(CONFIG, None) == []


@pytest.mark.asyncio
@respx.mock
async def test_poll_node() -> None:
    respx.get(f"{BASE_URL}/nodes/pve1/status").mock(
        return_value=httpx.Response(200, json={"data": NODE_STATUS})
    )
    plugin = ProxmoxPlugin()
    target = TargetDescriptor(
        external_ref="node:pve1", display_name="pve1", attributes={"resource_type": "node", "node": "pve1"}
    )

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is True
    assert result.metrics["cpu_percent"] == pytest.approx(5.0)
    assert result.metrics["mem_used_percent"] == pytest.approx(30.0)


@pytest.mark.asyncio
@respx.mock
async def test_poll_running_qemu() -> None:
    _mock_inventory(respx)
    plugin = ProxmoxPlugin()
    target = TargetDescriptor(
        external_ref="qemu:pve1:100",
        display_name="vm1",
        attributes={"resource_type": "qemu", "node": "pve1", "vmid": 100},
    )

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is True
    assert result.metrics["cpu_percent"] == pytest.approx(10.0)
    assert result.metrics["mem_used_percent"] == pytest.approx(50.0)
    assert result.metrics["uptime_seconds"] == 3600.0


@pytest.mark.asyncio
@respx.mock
async def test_poll_stopped_lxc_reports_not_running() -> None:
    _mock_inventory(respx)
    plugin = ProxmoxPlugin()
    target = TargetDescriptor(
        external_ref="lxc:pve1:200",
        display_name="ct1",
        attributes={"resource_type": "lxc", "node": "pve1", "vmid": 200},
    )

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is False


@pytest.mark.asyncio
async def test_poll_without_credential() -> None:
    plugin = ProxmoxPlugin()
    target = TargetDescriptor(external_ref="node:pve1", display_name="pve1")

    result = await plugin.poll(CONFIG, None, target)

    assert result.success is False
    assert result.error_message == "No credential configured"


@pytest.mark.asyncio
async def test_validate_config_requires_token_secret() -> None:
    plugin = ProxmoxPlugin()

    result = await plugin.validate_config(CONFIG, None)

    assert result.ok is False


@pytest.mark.asyncio
async def test_wallet_entry_has_no_host_and_lists_no_targets() -> None:
    """A wallet credential needs token_id on the credential itself, since there's no config.token_id
    to fall back on without a host - see ProxmoxTokenCredential."""
    plugin = ProxmoxPlugin()
    wallet_credential = {"token_id": "banana@pve!token1", "token_secret": "sekrit-value"}

    result = await plugin.validate_config({}, wallet_credential)
    assert result.ok is True

    assert await plugin.list_targets({}, wallet_credential) == []


@pytest.mark.asyncio
async def test_wallet_entry_without_a_token_id_anywhere_is_rejected() -> None:
    plugin = ProxmoxPlugin()

    result = await plugin.validate_config({}, {"token_secret": "sekrit-value"})

    assert result.ok is False


@pytest.mark.asyncio
@respx.mock
async def test_probe_credential_succeeds_with_token_id_on_the_credential() -> None:
    _mock_inventory(respx)

    ok = await ProxmoxPlugin().probe_credential(
        {"token_id": "banana@pve!token1", "token_secret": "sekrit-value"}, "pve.local", 8006
    )

    assert ok is True


@pytest.mark.asyncio
@respx.mock
async def test_probe_credential_fails_on_http_error() -> None:
    respx.get(f"{BASE_URL}/nodes").mock(return_value=httpx.Response(401))

    ok = await ProxmoxPlugin().probe_credential(
        {"token_id": "banana@pve!token1", "token_secret": "wrong"}, "pve.local", 8006
    )

    assert ok is False


@pytest.mark.asyncio
async def test_validate_config_makes_a_real_connection_when_host_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = ProxmoxPlugin()
    credential = {"token_id": "banana@pve!token1", "token_secret": "sekrit-value"}

    monkeypatch.setattr(plugin, "probe_credential", AsyncMock(return_value=False))
    failed = await plugin.validate_config(CONFIG, credential)
    assert failed.ok is False
    assert "pve.local:8006" in (failed.message or "")

    monkeypatch.setattr(plugin, "probe_credential", AsyncMock(return_value=True))
    assert (await plugin.validate_config(CONFIG, credential)).ok is True


@pytest.mark.asyncio
async def test_validate_config_skips_the_live_check_for_a_wallet_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = ProxmoxPlugin()
    credential = {"token_id": "banana@pve!token1", "token_secret": "sekrit-value"}

    probe = AsyncMock(side_effect=AssertionError("probe_credential must not be called for a wallet entry"))
    monkeypatch.setattr(plugin, "probe_credential", probe)

    result = await plugin.validate_config({}, credential)

    assert result.ok is True
    probe.assert_not_called()
