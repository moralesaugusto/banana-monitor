import asyncio
import time
from functools import lru_cache

from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.session import Databases, get_databases
from app.domain.bootstrap import ensure_default_site
from app.domain.enums import DeviceType, EntityType, HealthStatus
from app.domain.models import Device, utcnow
from app.metrics.writer import MetricsWriter, get_metrics_writer
from app.scheduler.supervisor import PollingSupervisor, get_supervisor

SELF_HEALTH_DEVICE_NAME = "Banana (self)"
SELF_HEALTH_INTERVAL_SECONDS = 30.0


async def ensure_self_health_device(databases: Databases) -> int:
    async with databases.app_session_factory() as session:
        result = await session.execute(
            select(Device).where(Device.device_type == DeviceType.PLATFORM_SELF)
        )
        device = result.scalar_one_or_none()
        if device is not None:
            return device.id

        site = await ensure_default_site(session)
        device = Device(
            site_id=site.id,
            display_name=SELF_HEALTH_DEVICE_NAME,
            device_type=DeviceType.PLATFORM_SELF,
            managed=True,
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return device.id


class SelfHealthMonitor:
    """The platform monitors its own event-loop responsiveness, DB sizes, and
    active poll-task count as a normal Device - reusing the existing model
    rather than a parallel concept, per AGENTS.md's self-health requirement.
    """

    def __init__(
        self,
        databases: Databases,
        metrics_writer: MetricsWriter,
        settings: Settings,
        supervisor: PollingSupervisor,
    ) -> None:
        self._databases = databases
        self._metrics_writer = metrics_writer
        self._settings = settings
        self._supervisor = supervisor
        self._device_id: int | None = None

    async def run_once(self) -> None:
        if self._device_id is None:
            self._device_id = await ensure_self_health_device(self._databases)
        device_id = self._device_id

        loop_lag_ms = await self._measure_event_loop_lag()

        self._metrics_writer.enqueue_check_result(
            entity_type=EntityType.DEVICE, entity_id=device_id, success=True, latency_ms=loop_lag_ms
        )
        self._metrics_writer.enqueue_metric_sample(
            entity_type=EntityType.DEVICE,
            entity_id=device_id,
            metric_name="event_loop_lag_ms",
            value=loop_lag_ms,
            unit="ms",
        )
        for name, size_bytes in self._db_sizes().items():
            self._metrics_writer.enqueue_metric_sample(
                entity_type=EntityType.DEVICE,
                entity_id=device_id,
                metric_name=f"{name}_db_size_mb",
                value=size_bytes / (1024 * 1024),
                unit="MB",
            )
        self._metrics_writer.enqueue_metric_sample(
            entity_type=EntityType.DEVICE,
            entity_id=device_id,
            metric_name="active_poll_tasks",
            value=float(self._supervisor.active_task_count()),
        )

        async with self._databases.app_session_factory() as session:
            device = await session.get(Device, device_id)
            if device is not None:
                device.status = HealthStatus.UP
                device.last_seen_at = utcnow()
                await session.commit()

    async def _measure_event_loop_lag(self) -> float:
        started = time.monotonic()
        await asyncio.sleep(0)
        return (time.monotonic() - started) * 1000

    def _db_sizes(self) -> dict[str, int]:
        paths = {
            "app": self._settings.app_db_path,
            "metrics": self._settings.metrics_db_path,
            "credentials": self._settings.credentials_db_path,
        }
        return {name: path.stat().st_size if path.exists() else 0 for name, path in paths.items()}


@lru_cache
def get_self_health_monitor() -> SelfHealthMonitor:
    return SelfHealthMonitor(get_databases(), get_metrics_writer(), get_settings(), get_supervisor())
