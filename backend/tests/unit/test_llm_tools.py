import pytest

from app.credentials.models import CredentialsBase
from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_site
from app.domain.enums import AlertConditionType, DeviceType
from app.domain.metrics_models import MetricsBase
from app.domain.models import AlertRule, Device
from app.domain.models import Base as AppBase
from app.llm.tools import (
    READ_ONLY_TOOL_SCHEMAS,
    TOOL_SCHEMAS,
    WRITE_TOOL_NAMES,
    ToolExecutionError,
    dispatch_tool_call,
)


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with dbs.metrics_engine.begin() as conn:
        await conn.run_sync(MetricsBase.metadata.create_all)
    async with dbs.credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


@pytest.mark.asyncio
async def test_list_devices_empty(databases) -> None:
    result = await dispatch_tool_call(databases, "list_devices", {})
    assert result == []


@pytest.mark.asyncio
async def test_update_device_happy_path(databases) -> None:
    async with databases.app_session_factory() as session:
        site = await ensure_default_site(session)
        device = Device(site_id=site.id, display_name="old-name", device_type=DeviceType.LINUX)
        session.add(device)
        await session.commit()
        await session.refresh(device)
        device_id = device.id

    result = await dispatch_tool_call(
        databases, "update_device", {"device_id": device_id, "display_name": "new-name"}
    )
    assert result["display_name"] == "new-name"

    listed = await dispatch_tool_call(databases, "list_devices", {})
    assert listed[0]["display_name"] == "new-name"


@pytest.mark.asyncio
async def test_update_device_missing_raises(databases) -> None:
    with pytest.raises(ToolExecutionError):
        await dispatch_tool_call(databases, "update_device", {"device_id": 999, "display_name": "x"})


@pytest.mark.asyncio
async def test_set_alert_rule_enabled_happy_path(databases) -> None:
    async with databases.app_session_factory() as session:
        rule = AlertRule(
            name="device-down",
            condition_type=AlertConditionType.DEVICE_DOWN,
            entity_selector={},
            parameters={},
            enabled=True,
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        rule_id = rule.id

    result = await dispatch_tool_call(
        databases, "set_alert_rule_enabled", {"rule_id": rule_id, "enabled": False}
    )
    assert result["enabled"] is False


@pytest.mark.asyncio
async def test_unknown_tool_raises(databases) -> None:
    with pytest.raises(ToolExecutionError):
        await dispatch_tool_call(databases, "delete_everything", {})


@pytest.mark.asyncio
async def test_get_device_missing_raises(databases) -> None:
    with pytest.raises(ToolExecutionError):
        await dispatch_tool_call(databases, "get_device", {"device_id": 999})


@pytest.mark.asyncio
async def test_update_device_missing_required_argument_raises(databases) -> None:
    with pytest.raises(ToolExecutionError):
        await dispatch_tool_call(databases, "update_device", {})


@pytest.mark.asyncio
async def test_a_write_tool_is_refused_without_full_access(databases) -> None:
    with pytest.raises(ToolExecutionError, match="read-only mode"):
        await dispatch_tool_call(databases, "trigger_network_scan", {"network_id": 1}, full_access=False)


@pytest.mark.asyncio
async def test_a_read_tool_works_without_full_access(databases) -> None:
    result = await dispatch_tool_call(databases, "list_devices", {}, full_access=False)
    assert result == []


def test_read_only_schemas_exclude_every_write_tool() -> None:
    names = {schema["function"]["name"] for schema in READ_ONLY_TOOL_SCHEMAS}
    assert names.isdisjoint(WRITE_TOOL_NAMES)
    assert names | WRITE_TOOL_NAMES == {schema["function"]["name"] for schema in TOOL_SCHEMAS}
