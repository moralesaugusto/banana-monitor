import httpx
import pytest
import respx

from app.integrations.base import TargetDescriptor
from app.integrations.homebridge.plugin import HomebridgePlugin

BASE_URL = "http://hb.local:8581"

CONFIG = {"device_id": 3, "host": "hb.local", "port": 8581}
CREDENTIAL = {"username": "admin", "password": "sUpErSeCrEt-password"}

LOGIN_RESPONSE = {"access_token": "test-token-abc", "token_type": "Bearer"}
STATUS_RESPONSE = {"cpuLoad": 12.5, "memoryUsage": 42.0, "uptime": 3600}
ACCESSORIES_RESPONSE = [{"uniqueId": "1"}, {"uniqueId": "2"}, {"uniqueId": "3"}]


@pytest.mark.asyncio
@respx.mock
async def test_poll_reports_metrics() -> None:
    respx.post(f"{BASE_URL}/api/auth/login").mock(return_value=httpx.Response(200, json=LOGIN_RESPONSE))
    respx.get(f"{BASE_URL}/api/status/homebridge").mock(
        return_value=httpx.Response(200, json=STATUS_RESPONSE)
    )
    respx.get(f"{BASE_URL}/api/accessories").mock(
        return_value=httpx.Response(200, json=ACCESSORIES_RESPONSE)
    )
    plugin = HomebridgePlugin()
    target = TargetDescriptor(external_ref="homebridge:hb.local:8581", display_name="hb.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is True, result.error_message
    assert result.metrics["cpu_percent"] == 12.5
    assert result.metrics["mem_used_percent"] == 42.0
    assert result.metrics["accessories_total"] == 3.0


@pytest.mark.asyncio
@respx.mock
async def test_poll_omits_missing_metrics_defensively() -> None:
    """A Homebridge UI version that doesn't expose /api/status/homebridge (404)
    falls back to /api/status/server-information; if that's also unavailable,
    host metrics are simply omitted rather than guessed."""
    respx.post(f"{BASE_URL}/api/auth/login").mock(return_value=httpx.Response(200, json=LOGIN_RESPONSE))
    respx.get(f"{BASE_URL}/api/status/homebridge").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE_URL}/api/status/server-information").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE_URL}/api/accessories").mock(
        return_value=httpx.Response(200, json=ACCESSORIES_RESPONSE)
    )
    plugin = HomebridgePlugin()
    target = TargetDescriptor(external_ref="homebridge:hb.local:8581", display_name="hb.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is True
    assert "cpu_percent" not in result.metrics
    assert "mem_used_percent" not in result.metrics
    assert result.metrics["accessories_total"] == 3.0


@pytest.mark.asyncio
@respx.mock
async def test_poll_fails_on_bad_login() -> None:
    respx.post(f"{BASE_URL}/api/auth/login").mock(return_value=httpx.Response(401))
    plugin = HomebridgePlugin()
    target = TargetDescriptor(external_ref="homebridge:hb.local:8581", display_name="hb.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is False
    assert result.error_message is not None
    assert CREDENTIAL["password"] not in result.error_message


@pytest.mark.asyncio
async def test_poll_without_credential() -> None:
    plugin = HomebridgePlugin()
    target = TargetDescriptor(external_ref="homebridge:hb.local:8581", display_name="hb.local")

    result = await plugin.poll(CONFIG, None, target)

    assert result.success is False
    assert result.error_message == "No credential configured"


@pytest.mark.asyncio
@respx.mock
async def test_validate_config_requires_successful_login() -> None:
    respx.post(f"{BASE_URL}/api/auth/login").mock(return_value=httpx.Response(200, json=LOGIN_RESPONSE))
    plugin = HomebridgePlugin()

    result = await plugin.validate_config(CONFIG, CREDENTIAL)

    assert result.ok is True


@pytest.mark.asyncio
async def test_list_targets_returns_single_target_with_device_id() -> None:
    plugin = HomebridgePlugin()

    targets = await plugin.list_targets(CONFIG, CREDENTIAL)

    assert len(targets) == 1
    assert targets[0].device_id == 3


@pytest.mark.asyncio
@respx.mock
async def test_poll_never_leaks_credential_in_result() -> None:
    respx.post(f"{BASE_URL}/api/auth/login").mock(side_effect=httpx.ConnectError("boom"))
    plugin = HomebridgePlugin()
    target = TargetDescriptor(external_ref="homebridge:hb.local:8581", display_name="hb.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is False
    dumped = result.model_dump_json()
    assert CREDENTIAL["password"] not in dumped
    assert CREDENTIAL["username"] not in dumped


@pytest.mark.asyncio
async def test_wallet_entry_has_no_host_and_lists_no_targets() -> None:
    plugin = HomebridgePlugin()

    result = await plugin.validate_config({}, CREDENTIAL)
    assert result.ok is True

    assert await plugin.list_targets({}, CREDENTIAL) == []


@pytest.mark.asyncio
@respx.mock
async def test_probe_credential_succeeds() -> None:
    respx.post(f"{BASE_URL}/api/auth/login").mock(return_value=httpx.Response(200, json=LOGIN_RESPONSE))

    ok = await HomebridgePlugin().probe_credential(CREDENTIAL, "hb.local", 8581)

    assert ok is True


@pytest.mark.asyncio
@respx.mock
async def test_probe_credential_fails_on_bad_auth() -> None:
    respx.post(f"{BASE_URL}/api/auth/login").mock(return_value=httpx.Response(401))

    ok = await HomebridgePlugin().probe_credential(CREDENTIAL, "hb.local", 8581)

    assert ok is False
