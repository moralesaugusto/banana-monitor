import asyncio
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from app.credentials.models import CredentialsBase
from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_site
from app.domain.enums import DeviceType, IntegrationStatus
from app.domain.metrics_models import MetricsBase
from app.domain.models import Base as AppBase
from app.domain.models import Device, Integration
from app.integrations import registry
from app.integrations.base import DiscoveredItem, PollResult, TargetDescriptor, ValidationResult
from app.metrics.writer import MetricsWriter
from app.scheduler.supervisor import PollingSupervisor


class _EmptyConfig(BaseModel):
    pass


class StubPlugin:
    type_key: ClassVar[str] = "test_stub_integration"
    display_name: ClassVar[str] = "Stub"
    config_schema: ClassVar[type[BaseModel]] = _EmptyConfig
    credential_schema: ClassVar[type[BaseModel] | None] = None

    def __init__(self, device_id: int) -> None:
        self.device_id = device_id
        self.poll_calls = 0

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        return ValidationResult(ok=True)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        return [
            TargetDescriptor(
                external_ref=str(self.device_id), display_name="stub", device_id=self.device_id
            )
        ]

    async def discover(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[DiscoveredItem]:
        return []

    async def poll(
        self, config: dict[str, Any], credential: dict[str, Any] | None, target: TargetDescriptor
    ) -> PollResult:
        self.poll_calls += 1
        return PollResult(success=True, latency_ms=5.0, metrics={"stub_metric": 1.0})


@pytest.fixture
async def prepared_databases():
    databases = get_databases()
    async with databases.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with databases.metrics_engine.begin() as conn:
        await conn.run_sync(MetricsBase.metadata.create_all)
    async with databases.credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)
    yield databases
    await databases.dispose()


@pytest.mark.asyncio
async def test_add_integration_is_noop_when_not_running(prepared_databases) -> None:
    supervisor = PollingSupervisor(prepared_databases, MetricsWriter(prepared_databases))
    integration = Integration(integration_type="test_stub_integration", name="stub", config={})

    await supervisor.add_integration(integration)

    assert supervisor._integration_tasks == {}


@pytest.mark.asyncio
async def test_add_integration_spawns_and_polls_a_stub_target(prepared_databases) -> None:
    async with prepared_databases.app_session_factory() as session:
        site = await ensure_default_site(session)
        device = Device(site_id=site.id, display_name="dev1", device_type=DeviceType.LINUX)
        session.add(device)
        await session.commit()
        await session.refresh(device)
        device_id = device.id

    plugin = StubPlugin(device_id)
    registry.register(plugin)
    try:
        async with prepared_databases.app_session_factory() as session:
            integration = Integration(
                integration_type="test_stub_integration",
                name="stub",
                config={"interval_seconds": 0.05},
            )
            session.add(integration)
            await session.commit()
            await session.refresh(integration)

        supervisor = PollingSupervisor(prepared_databases, MetricsWriter(prepared_databases))
        supervisor._running = True

        await supervisor.add_integration(integration)
        assert integration.id in supervisor._integration_tasks

        await asyncio.sleep(0.2)
        assert plugin.poll_calls >= 1

        async with prepared_databases.app_session_factory() as session:
            refreshed_integration = await session.get(Integration, integration.id)
            assert refreshed_integration is not None
            assert refreshed_integration.status == IntegrationStatus.OK

        supervisor.remove_integration(integration.id)
        assert integration.id not in supervisor._integration_tasks
        await asyncio.sleep(0.05)
    finally:
        registry._REGISTRY.pop("test_stub_integration", None)


@pytest.mark.asyncio
async def test_resolve_target_device_auto_provisions_and_reuses(prepared_databases) -> None:
    async with prepared_databases.app_session_factory() as session:
        integration = Integration(integration_type="proxmox", name="pve1", config={})
        session.add(integration)
        await session.commit()
        await session.refresh(integration)

    supervisor = PollingSupervisor(prepared_databases, MetricsWriter(prepared_databases))
    target = TargetDescriptor(
        external_ref="qemu:pve1:100",
        display_name="vm1",
        attributes={"device_type": "proxmox_vm"},
    )

    device_id_first = await supervisor._resolve_target_device(integration, target)
    device_id_second = await supervisor._resolve_target_device(integration, target)

    assert device_id_first is not None
    assert device_id_first == device_id_second

    async with prepared_databases.app_session_factory() as session:
        device = await session.get(Device, device_id_first)
        assert device is not None
        assert device.display_name == "vm1"
        assert device.device_type == DeviceType.PROXMOX_VM


@pytest.mark.asyncio
async def test_spawn_integration_flags_an_error_when_credential_missing(prepared_databases) -> None:
    plugin = StubPlugin(device_id=1)
    registry.register(plugin)
    try:
        integration = Integration(
            integration_type="test_stub_integration",
            name="stub",
            config={},
            credential_id=999,
        )
        async with prepared_databases.app_session_factory() as session:
            session.add(integration)
            await session.commit()
            await session.refresh(integration)
        supervisor = PollingSupervisor(prepared_databases, MetricsWriter(prepared_databases))
        supervisor._running = True

        await supervisor.add_integration(integration)

        assert supervisor._integration_tasks == {}  # nothing is polled...
        async with prepared_databases.app_session_factory() as session:
            row = await session.get(Integration, integration.id)
        assert row is not None and row.status == IntegrationStatus.ERROR  # ...and it says so
        assert row.last_error is not None and "Credential unavailable" in row.last_error
    finally:
        registry._REGISTRY.pop("test_stub_integration", None)
