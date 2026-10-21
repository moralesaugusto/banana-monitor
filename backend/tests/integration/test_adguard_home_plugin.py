import httpx
import pytest
import respx

from app.integrations.adguard_home.plugin import AdGuardHomePlugin
from app.integrations.base import TargetDescriptor

BASE_URL = "http://agh.local:3000"

CONFIG = {"device_id": 7, "host": "agh.local", "port": 3000}
CREDENTIAL = {"username": "admin", "password": "sUpErSeCrEt-password"}

STATUS = {"protection_enabled": True, "running": True}
STATS = {"num_dns_queries": 1000, "num_blocked_filtering": 250, "avg_processing_time": 0.004}


@pytest.mark.asyncio
@respx.mock
async def test_poll_reports_metrics() -> None:
    respx.get(f"{BASE_URL}/control/status").mock(return_value=httpx.Response(200, json=STATUS))
    respx.get(f"{BASE_URL}/control/stats").mock(return_value=httpx.Response(200, json=STATS))
    plugin = AdGuardHomePlugin()
    target = TargetDescriptor(external_ref="adguard_home:agh.local:3000", display_name="agh.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is True
    assert result.metrics["queries_total"] == 1000.0
    assert result.metrics["blocked_percent"] == pytest.approx(25.0)
    assert result.metrics["avg_processing_time_ms"] == pytest.approx(4.0)
    assert result.metrics["protection_enabled"] == 1.0
    assert result.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_poll_fails_on_http_error() -> None:
    respx.get(f"{BASE_URL}/control/status").mock(return_value=httpx.Response(403))
    plugin = AdGuardHomePlugin()
    target = TargetDescriptor(external_ref="adguard_home:agh.local:3000", display_name="agh.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is False
    assert result.error_message is not None
    assert CREDENTIAL["password"] not in result.error_message


@pytest.mark.asyncio
async def test_poll_without_credential() -> None:
    plugin = AdGuardHomePlugin()
    target = TargetDescriptor(external_ref="adguard_home:agh.local:3000", display_name="agh.local")

    result = await plugin.poll(CONFIG, None, target)

    assert result.success is False
    assert result.error_message == "No credential configured"


@pytest.mark.asyncio
@respx.mock
async def test_validate_config_checks_status_endpoint() -> None:
    respx.get(f"{BASE_URL}/control/status").mock(return_value=httpx.Response(200, json=STATUS))
    plugin = AdGuardHomePlugin()

    result = await plugin.validate_config(CONFIG, CREDENTIAL)

    assert result.ok is True


@pytest.mark.asyncio
async def test_validate_config_requires_credential() -> None:
    plugin = AdGuardHomePlugin()

    result = await plugin.validate_config(CONFIG, None)

    assert result.ok is False


@pytest.mark.asyncio
async def test_list_targets_returns_single_target_with_device_id() -> None:
    plugin = AdGuardHomePlugin()

    targets = await plugin.list_targets(CONFIG, CREDENTIAL)

    assert len(targets) == 1
    assert targets[0].device_id == 7


@pytest.mark.asyncio
@respx.mock
async def test_poll_never_leaks_credential_in_result() -> None:
    """Regression coverage: the decrypted password must never end up in a
    PollResult (metrics, error_message) even when something goes wrong."""
    respx.get(f"{BASE_URL}/control/status").mock(side_effect=httpx.ConnectError("boom"))
    plugin = AdGuardHomePlugin()
    target = TargetDescriptor(external_ref="adguard_home:agh.local:3000", display_name="agh.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is False
    dumped = result.model_dump_json()
    assert CREDENTIAL["password"] not in dumped
    assert CREDENTIAL["username"] not in dumped


@pytest.mark.asyncio
async def test_wallet_entry_has_no_host_and_lists_no_targets() -> None:
    plugin = AdGuardHomePlugin()

    result = await plugin.validate_config({}, CREDENTIAL)
    assert result.ok is True

    assert await plugin.list_targets({}, CREDENTIAL) == []


@pytest.mark.asyncio
@respx.mock
async def test_probe_credential_succeeds() -> None:
    respx.get(f"{BASE_URL}/control/status").mock(return_value=httpx.Response(200, json=STATUS))

    ok = await AdGuardHomePlugin().probe_credential(CREDENTIAL, "agh.local", 3000)

    assert ok is True


@pytest.mark.asyncio
@respx.mock
async def test_probe_credential_fails_on_bad_auth() -> None:
    respx.get(f"{BASE_URL}/control/status").mock(return_value=httpx.Response(401))

    ok = await AdGuardHomePlugin().probe_credential(CREDENTIAL, "agh.local", 3000)

    assert ok is False
