import pytest

from app.credentials.models import CredentialsBase
from app.db.session import get_databases
from app.domain.enums import DeviceType, EntityType, HealthStatus
from app.domain.metrics_models import MetricsBase
from app.domain.models import Base as AppBase
from app.domain.models import Device
from app.metrics.writer import MetricsWriter
from app.scheduler.supervisor import PollingSupervisor
from app.selfhealth.monitor import SELF_HEALTH_DEVICE_NAME, SelfHealthMonitor, ensure_self_health_device


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
async def test_ensure_self_health_device_creates_and_reuses(databases) -> None:
    first_id = await ensure_self_health_device(databases)
    second_id = await ensure_self_health_device(databases)

    assert first_id == second_id

    async with databases.app_session_factory() as session:
        device = await session.get(Device, first_id)
        assert device.display_name == SELF_HEALTH_DEVICE_NAME
        assert device.device_type == DeviceType.PLATFORM_SELF


class RecordingMetricsWriter:
    def __init__(self) -> None:
        self.samples: list[dict] = []
        self.check_results: list[dict] = []

    def enqueue_check_result(self, **kwargs) -> None:
        self.check_results.append(kwargs)

    def enqueue_metric_sample(self, **kwargs) -> None:
        self.samples.append(kwargs)


@pytest.mark.asyncio
async def test_run_once_reports_metrics_and_marks_device_up(databases) -> None:
    writer = RecordingMetricsWriter()
    from app.config import get_settings

    supervisor = PollingSupervisor(databases, MetricsWriter(databases))
    monitor = SelfHealthMonitor(databases, writer, get_settings(), supervisor)

    await monitor.run_once()

    metric_names = {s["metric_name"] for s in writer.samples}
    assert "event_loop_lag_ms" in metric_names
    assert "active_poll_tasks" in metric_names
    assert any(name.endswith("_db_size_mb") for name in metric_names)
    assert writer.check_results[0]["entity_type"] == EntityType.DEVICE
    assert writer.check_results[0]["success"] is True

    device_id = writer.check_results[0]["entity_id"]
    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        assert device.status == HealthStatus.UP
        assert device.last_seen_at is not None
