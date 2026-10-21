import httpx
import pytest
import respx

from app.integrations.base import TargetDescriptor
from app.integrations.omada.plugin import OmadaPlugin

BASE_URL = "https://omada.local:8043"

CONFIG = {"device_id": 5, "host": "omada.local", "port": 8043, "site": "Default"}
CREDENTIAL = {"username": "admin", "password": "sUpErSeCrEt-password"}

LOGIN_RESPONSE = {"errorCode": 0, "msg": "Success.", "result": {"token": "test-token-xyz"}}
SITES_RESPONSE = {
    "errorCode": 0,
    "result": {"totalRows": 1, "data": [{"siteId": "site-1", "name": "Default"}]},
}
OVERVIEW_RESPONSE = {
    "errorCode": 0,
    "result": {"clientNum": 8, "connectedDeviceNum": 4, "disconnectedDeviceNum": 0},
}


def _mock_login_and_sites(router: respx.MockRouter) -> None:
    router.post(f"{BASE_URL}/api/v2/login").mock(return_value=httpx.Response(200, json=LOGIN_RESPONSE))
    router.get(f"{BASE_URL}/api/v2/sites").mock(return_value=httpx.Response(200, json=SITES_RESPONSE))


@pytest.mark.asyncio
@respx.mock
async def test_poll_reports_metrics() -> None:
    _mock_login_and_sites(respx)
    respx.get(f"{BASE_URL}/api/v2/sites/site-1/dashboard/overviewDiagram").mock(
        return_value=httpx.Response(200, json=OVERVIEW_RESPONSE)
    )
    plugin = OmadaPlugin()
    target = TargetDescriptor(external_ref="omada:omada.local:8043", display_name="omada.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is True, result.error_message
    assert result.metrics["clients_total"] == 8.0
    assert result.metrics["devices_online"] == 4.0


@pytest.mark.asyncio
@respx.mock
async def test_poll_falls_back_to_device_list_when_dashboard_lacks_counts() -> None:
    _mock_login_and_sites(respx)
    respx.get(f"{BASE_URL}/api/v2/sites/site-1/dashboard/overviewDiagram").mock(
        return_value=httpx.Response(200, json={"errorCode": 0, "result": {}})
    )
    respx.get(f"{BASE_URL}/api/v2/sites/site-1/devices").mock(
        return_value=httpx.Response(
            200,
            json={
                "errorCode": 0,
                "result": [
                    {"mac": "aa", "status": 1},
                    {"mac": "bb", "status": "connected"},
                    {"mac": "cc", "status": "offline"},
                ],
            },
        )
    )
    plugin = OmadaPlugin()
    target = TargetDescriptor(external_ref="omada:omada.local:8043", display_name="omada.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is True, result.error_message
    assert "clients_total" not in result.metrics
    assert result.metrics["devices_online"] == 2.0


@pytest.mark.asyncio
@respx.mock
async def test_poll_fails_cleanly_on_unexpected_json_shape() -> None:
    """The controller returning a shape we don't recognize must become a
    clean poll failure with a clear message, never a raised exception."""
    respx.post(f"{BASE_URL}/api/v2/login").mock(return_value=httpx.Response(200, json=LOGIN_RESPONSE))
    respx.get(f"{BASE_URL}/api/v2/sites").mock(
        return_value=httpx.Response(200, json={"errorCode": 0, "result": "not-a-list-or-page"})
    )
    plugin = OmadaPlugin()
    target = TargetDescriptor(external_ref="omada:omada.local:8043", display_name="omada.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is False
    assert result.error_message is not None


@pytest.mark.asyncio
@respx.mock
async def test_poll_fails_on_api_error_code() -> None:
    respx.post(f"{BASE_URL}/api/v2/login").mock(
        return_value=httpx.Response(200, json={"errorCode": -1, "msg": "Invalid credentials"})
    )
    plugin = OmadaPlugin()
    target = TargetDescriptor(external_ref="omada:omada.local:8043", display_name="omada.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is False
    assert "Invalid credentials" in (result.error_message or "")
    assert CREDENTIAL["password"] not in (result.error_message or "")


@pytest.mark.asyncio
async def test_poll_without_credential() -> None:
    plugin = OmadaPlugin()
    target = TargetDescriptor(external_ref="omada:omada.local:8043", display_name="omada.local")

    result = await plugin.poll(CONFIG, None, target)

    assert result.success is False
    assert result.error_message == "No credential configured"


@pytest.mark.asyncio
@respx.mock
async def test_validate_config_requires_successful_login() -> None:
    respx.post(f"{BASE_URL}/api/v2/login").mock(return_value=httpx.Response(200, json=LOGIN_RESPONSE))
    plugin = OmadaPlugin()

    result = await plugin.validate_config(CONFIG, CREDENTIAL)

    assert result.ok is True


@pytest.mark.asyncio
async def test_list_targets_returns_single_target_with_device_id() -> None:
    plugin = OmadaPlugin()

    targets = await plugin.list_targets(CONFIG, CREDENTIAL)

    assert len(targets) == 1
    assert targets[0].device_id == 5


@pytest.mark.asyncio
@respx.mock
async def test_poll_never_leaks_credential_in_result() -> None:
    respx.post(f"{BASE_URL}/api/v2/login").mock(side_effect=httpx.ConnectError("boom"))
    plugin = OmadaPlugin()
    target = TargetDescriptor(external_ref="omada:omada.local:8043", display_name="omada.local")

    result = await plugin.poll(CONFIG, CREDENTIAL, target)

    assert result.success is False
    dumped = result.model_dump_json()
    assert CREDENTIAL["password"] not in dumped
    assert CREDENTIAL["username"] not in dumped


@pytest.mark.asyncio
async def test_wallet_entry_has_no_host_and_lists_no_targets() -> None:
    plugin = OmadaPlugin()

    result = await plugin.validate_config({}, CREDENTIAL)
    assert result.ok is True

    assert await plugin.list_targets({}, CREDENTIAL) == []


@pytest.mark.asyncio
@respx.mock
async def test_probe_credential_succeeds() -> None:
    respx.post(f"{BASE_URL}/api/v2/login").mock(return_value=httpx.Response(200, json=LOGIN_RESPONSE))

    ok = await OmadaPlugin().probe_credential(CREDENTIAL, "omada.local", 8043)

    assert ok is True


@pytest.mark.asyncio
@respx.mock
async def test_probe_credential_fails_on_bad_auth() -> None:
    respx.post(f"{BASE_URL}/api/v2/login").mock(return_value=httpx.Response(401))

    ok = await OmadaPlugin().probe_credential(CREDENTIAL, "omada.local", 8043)

    assert ok is False
