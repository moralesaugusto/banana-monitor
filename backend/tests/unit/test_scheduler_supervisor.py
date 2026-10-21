from typing import Any

import pytest

from app.credentials.models import CredentialsBase
from app.db.session import get_databases
from app.domain.enums import EntityType, HealthStatus, ServiceType
from app.domain.metrics_models import MetricsBase
from app.domain.models import Base as AppBase
from app.domain.models import Service
from app.integrations.base import PollResult, TargetDescriptor
from app.metrics.writer import MetricsWriter
from app.scheduler.supervisor import PollingSupervisor


class FlakyPlugin:
    """Fails a fixed number of times, then succeeds - exercises retry/backoff."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def poll(
        self, config: dict[str, Any], credential: dict[str, Any] | None, target: TargetDescriptor
    ) -> PollResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("boom")
        return PollResult(success=True, latency_ms=1.0)


class AlwaysFailsPlugin:
    async def poll(
        self, config: dict[str, Any], credential: dict[str, Any] | None, target: TargetDescriptor
    ) -> PollResult:
        raise ConnectionError("always broken")


class RecordingMetricsWriter:
    def __init__(self) -> None:
        self.check_results: list[dict[str, Any]] = []
        self.metric_samples: list[dict[str, Any]] = []

    def enqueue_check_result(self, **kwargs: Any) -> None:
        self.check_results.append(kwargs)

    def enqueue_metric_sample(self, **kwargs: Any) -> None:
        self.metric_samples.append(kwargs)


@pytest.mark.asyncio
async def test_poll_once_retries_then_succeeds() -> None:
    supervisor = PollingSupervisor(get_databases(), MetricsWriter(get_databases()))
    plugin = FlakyPlugin(fail_times=2)
    target = TargetDescriptor(external_ref="1", display_name="test")

    result = await supervisor._poll_once(plugin, {}, target, timeout=1.0)  # type: ignore[arg-type]

    assert result.success is True
    assert plugin.calls == 3


@pytest.mark.asyncio
async def test_poll_once_never_raises_when_target_always_fails() -> None:
    supervisor = PollingSupervisor(get_databases(), MetricsWriter(get_databases()))
    target = TargetDescriptor(external_ref="1", display_name="test")

    result = await supervisor._poll_once(AlwaysFailsPlugin(), {}, target, timeout=1.0)  # type: ignore[arg-type]

    assert result.success is False
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_persist_updates_service_status_and_enqueues_metrics(tmp_path) -> None:
    databases = get_databases()
    async with databases.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with databases.metrics_engine.begin() as conn:
        await conn.run_sync(MetricsBase.metadata.create_all)
    async with databases.credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)

    async with databases.app_session_factory() as session:
        service = Service(
            name="web",
            service_type=ServiceType.HTTPS,
            config={"url": "https://example.com"},
        )
        session.add(service)
        await session.commit()
        await session.refresh(service)
        service_id = service.id

    writer = RecordingMetricsWriter()
    supervisor = PollingSupervisor(databases, writer)  # type: ignore[arg-type]

    await supervisor._persist_service(service_id, PollResult(success=True, latency_ms=42.0))

    assert writer.check_results[0]["entity_type"] == EntityType.SERVICE
    assert writer.check_results[0]["success"] is True
    assert writer.metric_samples[0]["value"] == 42.0

    async with databases.app_session_factory() as session:
        refreshed = await session.get(Service, service_id)
        assert refreshed is not None
        assert refreshed.status == HealthStatus.UP
        assert refreshed.last_checked_at is not None

    await databases.dispose()
