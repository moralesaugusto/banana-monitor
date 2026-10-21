from unittest.mock import AsyncMock

import pytest

from app.integrations.base import TargetDescriptor
from app.integrations.windows_winrm import plugin as winrm_plugin
from app.integrations.windows_winrm.parsers import parse_health

OUTPUT = "cpu=12\nmem=16000000 4000000\ndisk=500000000000 125000000000\nhostname=WIN-LAB\n"
CONFIG = {"device_id": 1, "host": "10.77.0.50"}
CREDENTIAL = {"username": "banana", "password": "pw"}


def test_parse_health():
    metrics, hostname = parse_health(OUTPUT)
    assert hostname == "WIN-LAB"
    assert metrics == {
        "cpu_percent": 12.0,
        "mem_total_kb": 16000000.0,
        "mem_used_percent": 75.0,
        "disk_used_percent": 75.0,
    }


def test_parse_health_tolerates_missing_fields():
    assert parse_health("hostname=X\ncpu=\n") == ({}, "X")


@pytest.mark.asyncio
async def test_poll_success(monkeypatch):
    async def fake(config, credential, script):
        return 0, OUTPUT, ""

    monkeypatch.setattr(winrm_plugin, "run_powershell", fake)
    result = await winrm_plugin.WindowsWinrmPlugin().poll(
        CONFIG, CREDENTIAL, TargetDescriptor(external_ref="1", display_name="w")
    )
    assert result.success and result.hostname == "WIN-LAB" and result.metrics["cpu_percent"] == 12.0


@pytest.mark.asyncio
async def test_poll_reports_script_error(monkeypatch):
    async def fake(config, credential, script):
        return 1, "", "Access is denied"

    monkeypatch.setattr(winrm_plugin, "run_powershell", fake)
    result = await winrm_plugin.WindowsWinrmPlugin().poll(
        CONFIG, CREDENTIAL, TargetDescriptor(external_ref="1", display_name="w")
    )
    assert not result.success and "Access is denied" in (result.error_message or "")


@pytest.mark.asyncio
async def test_validate_requires_password(monkeypatch):
    plugin = winrm_plugin.WindowsWinrmPlugin()
    assert not (await plugin.validate_config(CONFIG, {"username": "x"})).ok
    # validate_config() now makes a real connection attempt when host is set (see
    # test_probe_credential_* below for that behavior) - this test is only about the field check.
    monkeypatch.setattr(plugin, "probe_credential", AsyncMock(return_value=True))
    assert (await plugin.validate_config(CONFIG, CREDENTIAL)).ok


@pytest.mark.asyncio
async def test_wallet_entry_has_no_host_and_lists_no_targets():
    plugin = winrm_plugin.WindowsWinrmPlugin()

    result = await plugin.validate_config({}, CREDENTIAL)
    assert result.ok is True

    assert await plugin.list_targets({}, CREDENTIAL) == []


@pytest.mark.asyncio
async def test_host_without_device_id_is_rejected():
    plugin = winrm_plugin.WindowsWinrmPlugin()
    result = await plugin.validate_config({"host": "10.77.0.50"}, CREDENTIAL)
    assert result.ok is False


@pytest.mark.asyncio
async def test_probe_credential_succeeds(monkeypatch):
    async def fake(config, credential, script):
        return 0, OUTPUT, ""

    monkeypatch.setattr(winrm_plugin, "run_powershell", fake)
    ok = await winrm_plugin.WindowsWinrmPlugin().probe_credential(CREDENTIAL, "10.77.0.50", 5986)
    assert ok is True


@pytest.mark.asyncio
async def test_probe_credential_fails_on_bad_exit_status(monkeypatch):
    async def fake(config, credential, script):
        return 1, "", "Access is denied"

    monkeypatch.setattr(winrm_plugin, "run_powershell", fake)
    ok = await winrm_plugin.WindowsWinrmPlugin().probe_credential(CREDENTIAL, "10.77.0.50", 5986)
    assert ok is False


@pytest.mark.asyncio
async def test_validate_config_makes_a_real_connection_when_host_is_set(monkeypatch):
    plugin = winrm_plugin.WindowsWinrmPlugin()

    monkeypatch.setattr(plugin, "probe_credential", AsyncMock(return_value=False))
    failed = await plugin.validate_config(CONFIG, CREDENTIAL)
    assert failed.ok is False
    assert "10.77.0.50:5986" in (failed.message or "")

    monkeypatch.setattr(plugin, "probe_credential", AsyncMock(return_value=True))
    assert (await plugin.validate_config(CONFIG, CREDENTIAL)).ok is True


@pytest.mark.asyncio
async def test_validate_config_skips_the_live_check_for_a_wallet_entry(monkeypatch):
    plugin = winrm_plugin.WindowsWinrmPlugin()

    probe = AsyncMock(side_effect=AssertionError("probe_credential must not be called for a wallet entry"))
    monkeypatch.setattr(plugin, "probe_credential", probe)

    result = await plugin.validate_config({}, CREDENTIAL)

    assert result.ok is True
    probe.assert_not_called()
