import asyncio
import contextlib
import random
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from app.alerting.engine import get_alert_engine
from app.credentials.crypto import MasterKeyError, get_secret_box
from app.credentials.service import CredentialNotFoundError, CredentialService
from app.db.session import Databases, get_databases
from app.discovery.hostnames import apply_hostname
from app.domain.bootstrap import ensure_default_site
from app.domain.enums import DeviceType, EntityType, HealthStatus, IntegrationStatus, ServiceType
from app.domain.models import Device, Integration, IntegrationTarget, Service, utcnow
from app.integrations import registry
from app.integrations.base import IntegrationPlugin, PollResult, TargetDescriptor
from app.logging_setup import get_logger
from app.metrics.writer import MetricsWriter, get_metrics_writer

logger = get_logger(__name__)

DEFAULT_INTERVAL_SECONDS = 30.0
MAX_POLL_TIMEOUT_SECONDS = 30.0
GLOBAL_CONCURRENCY_LIMIT = 50

SERVICE_TYPE_TO_PLUGIN: dict[ServiceType, str] = {
    ServiceType.HTTP: "http_tcp",
    ServiceType.HTTPS: "http_tcp",
    ServiceType.TCP: "http_tcp",
    ServiceType.DNS: "dns",
    ServiceType.DHCP: "dhcp",
}


class PollingSupervisor:
    """Owns one asyncio.Task per monitored target - either a Service (generic
    HTTP/TCP checks) or a target produced by an Integration's list_targets()
    (e.g. one Linux host per generic_ssh integration, many VMs per Proxmox
    integration once that plugin lands).

    Inert until start() is called (e.g. tests that never run the app lifespan),
    so add_target()/add_integration()/etc. calls from route handlers are safe
    no-ops outside a running app.
    """

    def __init__(self, databases: Databases, metrics_writer: MetricsWriter) -> None:
        self._databases = databases
        self._metrics_writer = metrics_writer
        self._service_tasks: dict[int, asyncio.Task[None]] = {}
        self._integration_tasks: dict[int, list[asyncio.Task[None]]] = {}
        self._integration_locks: dict[int, asyncio.Lock] = {}
        self._integration_generation: dict[int, int] = {}
        self._semaphore = asyncio.Semaphore(GLOBAL_CONCURRENCY_LIMIT)
        self._running = False

    async def start(self) -> None:
        self._running = True
        async with self._databases.app_session_factory() as session:
            service_result = await session.execute(select(Service).where(Service.managed.is_(True)))
            for service in service_result.scalars().all():
                self._spawn_service(service)

            integration_result = await session.execute(
                select(Integration).where(Integration.enabled.is_(True))
            )
            for integration in integration_result.scalars().all():
                await self._spawn_integration(integration)

    async def stop(self) -> None:
        self._running = False
        all_tasks = list(self._service_tasks.values())
        for tasks in self._integration_tasks.values():
            all_tasks.extend(tasks)
        for task in all_tasks:
            task.cancel()
        for task in all_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._service_tasks.clear()
        self._integration_tasks.clear()

    def active_task_count(self) -> int:
        return len(self._service_tasks) + sum(len(tasks) for tasks in self._integration_tasks.values())

    # --- Service-backed targets (http_tcp) -----------------------------------

    def add_target(self, service: Service) -> None:
        if not self._running or not service.managed or service.id in self._service_tasks:
            return
        self._spawn_service(service)

    def remove_target(self, service_id: int) -> None:
        task = self._service_tasks.pop(service_id, None)
        if task is not None:
            task.cancel()

    def reload_target(self, service: Service) -> None:
        self.remove_target(service.id)
        self.add_target(service)

    def _spawn_service(self, service: Service) -> None:
        plugin_key = SERVICE_TYPE_TO_PLUGIN.get(service.service_type)
        if plugin_key is None:
            return
        plugin = registry.get_plugin(plugin_key)
        if plugin is None:
            logger.warning("no_plugin_for_service_type", service_type=service.service_type)
            return
        task = asyncio.create_task(
            self._run_service_target(service.id, service.name, dict(service.config), plugin)
        )
        self._service_tasks[service.id] = task

    async def _run_service_target(
        self, service_id: int, name: str, config: dict[str, Any], plugin: IntegrationPlugin
    ) -> None:
        interval = float(config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))
        timeout = min(interval * 0.8, MAX_POLL_TIMEOUT_SECONDS)
        target = TargetDescriptor(external_ref=str(service_id), display_name=name)

        await asyncio.sleep(random.uniform(0, interval))

        while True:
            try:
                result = await self._poll_once(plugin, config, target, timeout)
                await self._persist_service(service_id, result)
            except Exception:  # noqa: BLE001 - one failed iteration (a locked database) must not end monitoring
                logger.warning("service_poll_iteration_failed", service_id=service_id, exc_info=True)
            await asyncio.sleep(interval)

    async def _persist_service(self, service_id: int, result: PollResult) -> None:
        self._metrics_writer.enqueue_check_result(
            entity_type=EntityType.SERVICE,
            entity_id=service_id,
            success=result.success,
            latency_ms=result.latency_ms,
            error_message=result.error_message,
        )
        if result.latency_ms is not None:
            self._metrics_writer.enqueue_metric_sample(
                entity_type=EntityType.SERVICE,
                entity_id=service_id,
                metric_name="latency_ms",
                value=result.latency_ms,
                unit="ms",
            )

        await get_alert_engine().evaluate_entity(EntityType.SERVICE, service_id)

        status = HealthStatus.UP if result.success else HealthStatus.DOWN
        async with self._databases.app_session_factory() as session:
            service = await session.get(Service, service_id)
            if service is not None:
                service.status = status
                service.last_checked_at = utcnow()
                await session.commit()

    async def check_service_now(self, service_id: int) -> HealthStatus | None:
        """One immediate check of a monitored service, outside its schedule (used by Rescan). Returns the
        new status, or None when the service is not monitored or has no check."""
        async with self._databases.app_session_factory() as session:
            service = await session.get(Service, service_id)
            if service is None or not service.managed:
                return None
            plugin_key = SERVICE_TYPE_TO_PLUGIN.get(service.service_type)
            plugin = registry.get_plugin(plugin_key) if plugin_key else None
            if plugin is None:
                return None
            config, name = dict(service.config), service.name
        interval = float(config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))
        target = TargetDescriptor(external_ref=str(service_id), display_name=name)
        result = await self._poll_once(plugin, config, target, min(interval * 0.8, MAX_POLL_TIMEOUT_SECONDS))
        await self._persist_service(service_id, result)
        return HealthStatus.UP if result.success else HealthStatus.DOWN

    # --- Integration-backed targets (generic_ssh, proxmox, ...) ----------------

    def _lock_for(self, integration_id: int) -> asyncio.Lock:
        return self._integration_locks.setdefault(integration_id, asyncio.Lock())

    async def add_integration(self, integration: Integration) -> None:
        # Starting an integration awaits network calls (list_targets). Serialize per integration so a second
        # add or reload during that time cannot start a second set of pollers that nothing tracks.
        async with self._lock_for(integration.id):
            if not self._running or integration.id in self._integration_tasks:
                return
            await self._spawn_integration(integration)

    def remove_integration(self, integration_id: int) -> None:
        # Bumping the generation tells a spawn that is still awaiting its network calls to discard its result.
        self._integration_generation[integration_id] = self._integration_generation.get(integration_id, 0) + 1
        tasks = self._integration_tasks.pop(integration_id, None)
        if tasks:
            for task in tasks:
                task.cancel()

    async def reload_integration(self, integration: Integration) -> None:
        async with self._lock_for(integration.id):
            self.remove_integration(integration.id)
            if self._running:
                await self._spawn_integration(integration)

    async def _spawn_integration(self, integration: Integration) -> None:
        generation = self._integration_generation.get(integration.id, 0)
        plugin = registry.get_plugin(integration.integration_type)
        if plugin is None:
            return

        credential = await self._decrypt_credential(integration)
        if integration.credential_id is not None and credential is None:
            logger.warning("integration_credential_missing", integration_id=integration.id)
            await self._update_integration_status(
                integration.id,
                PollResult(
                    success=False,
                    error_message="Credential unavailable: it was deleted or cannot be decrypted. "
                    "Pick another credential for this integration.",
                ),
            )
            return

        config = dict(integration.config)
        try:
            targets = await plugin.list_targets(config, credential)
        except Exception as exc:
            logger.warning("list_targets_failed", integration_id=integration.id, exc_info=True)
            await self._update_integration_status(
                integration.id, PollResult(success=False, error_message=f"Could not list targets: {exc}")
            )
            return

        tasks = []
        for target in targets:
            device_id = await self._resolve_target_device(integration, target)
            if device_id is None:
                continue
            tasks.append(
                asyncio.create_task(
                    self._run_integration_target(
                        integration.id, config, credential, plugin, target, device_id
                    )
                )
            )
        if self._integration_generation.get(integration.id, 0) != generation:
            for task in tasks:  # the integration was removed while it was starting
                task.cancel()
            return
        self._integration_tasks[integration.id] = tasks

    async def _decrypt_credential(self, integration: Integration) -> dict[str, Any] | None:
        if integration.credential_id is None:
            return None
        try:
            async with self._databases.credentials_session_factory() as session:
                return await CredentialService(get_secret_box()).get_decrypted(
                    session, integration.credential_id
                )
        except (CredentialNotFoundError, MasterKeyError):
            return None

    async def _resolve_target_device(
        self, integration: Integration, target: TargetDescriptor
    ) -> int | None:
        """Devices for plugins that already know the exact target (generic_ssh) are
        used directly; plugins that enumerate their own targets (proxmox) get an
        auto-provisioned Device tracked via IntegrationTarget, keyed by
        external_ref so re-running list_targets() reuses the same Device."""
        if target.device_id is not None:
            return target.device_id

        async with self._databases.app_session_factory() as session:
            result = await session.execute(
                select(IntegrationTarget).where(
                    IntegrationTarget.integration_id == integration.id,
                    IntegrationTarget.external_ref == target.external_ref,
                )
            )
            link = result.scalar_one_or_none()
            if link is not None:
                return link.device_id

            site = await ensure_default_site(session)
            device_type_value = target.attributes.get("device_type", DeviceType.OTHER.value)
            device = Device(
                site_id=site.id,
                display_name=target.display_name,
                device_type=DeviceType(device_type_value),
                managed=True,
            )
            session.add(device)
            await session.flush()

            session.add(
                IntegrationTarget(
                    integration_id=integration.id,
                    device_id=device.id,
                    external_ref=target.external_ref,
                )
            )
            await session.commit()
            return device.id

    async def _run_integration_target(
        self,
        integration_id: int,
        config: dict[str, Any],
        credential: dict[str, Any] | None,
        plugin: IntegrationPlugin,
        target: TargetDescriptor,
        device_id: int,
    ) -> None:
        interval = float(config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))
        timeout = min(interval * 0.8, MAX_POLL_TIMEOUT_SECONDS)

        await asyncio.sleep(random.uniform(0, interval))

        while True:
            try:
                result = await self._poll_once(plugin, config, target, timeout, credential=credential)
                if result.learned_config:
                    await self._remember_config(integration_id, config, result.learned_config)
                await self._persist_device(device_id, result)
                await self._update_integration_status(integration_id, result)
            except Exception:  # noqa: BLE001 - one failed iteration must not end monitoring of this target
                logger.warning(
                    "integration_poll_iteration_failed",
                    integration_id=integration_id,
                    device_id=device_id,
                    exc_info=True,
                )
            await asyncio.sleep(interval)

    async def _remember_config(
        self, integration_id: int, config: dict[str, Any], learned: dict[str, Any]
    ) -> None:
        """Stores values a plugin learned (a pinned SSH host key) in the integration's config, and in the
        copy this poller keeps using."""
        async with self._databases.app_session_factory() as session:
            integration = await session.get(Integration, integration_id)
            if integration is None:
                return
            integration.config = {**integration.config, **learned}  # a new dict, so the change is saved
            await session.commit()
        config.update(learned)

    async def _persist_device(self, device_id: int, result: PollResult) -> None:
        self._metrics_writer.enqueue_check_result(
            entity_type=EntityType.DEVICE,
            entity_id=device_id,
            success=result.success,
            latency_ms=result.latency_ms,
            error_message=result.error_message,
        )
        for metric_name, value in result.metrics.items():
            self._metrics_writer.enqueue_metric_sample(
                entity_type=EntityType.DEVICE,
                entity_id=device_id,
                metric_name=metric_name,
                value=value,
            )

        await get_alert_engine().evaluate_entity(EntityType.DEVICE, device_id)

        status = HealthStatus.UP if result.success else HealthStatus.DOWN
        async with self._databases.app_session_factory() as session:
            device = await session.get(Device, device_id)
            if device is not None:
                apply_hostname(device, result.hostname, "ssh")
                device.status = status
                if result.success:
                    # Only a successful poll means the device was actually there - matches
                    # reachability.py's convention. Touching it on every failed attempt too would make
                    # last_seen_at track "when we last tried", not "when we last found it", which is
                    # exactly what distinguishes a transient blip from a genuinely inactive device.
                    device.last_seen_at = utcnow()
                await session.commit()

    async def _update_integration_status(self, integration_id: int, result: PollResult) -> None:
        async with self._databases.app_session_factory() as session:
            integration = await session.get(Integration, integration_id)
            if integration is not None:
                integration.status = IntegrationStatus.OK if result.success else IntegrationStatus.ERROR
                integration.last_run_at = utcnow()
                integration.last_error = result.error_message
                await session.commit()

        await get_alert_engine().evaluate_entity(EntityType.INTEGRATION, integration_id)

    # --- shared poll execution -------------------------------------------------

    async def _poll_once(
        self,
        plugin: IntegrationPlugin,
        config: dict[str, Any],
        target: TargetDescriptor,
        timeout: float,
        credential: dict[str, Any] | None = None,
    ) -> PollResult:
        async def attempt() -> PollResult:
            return await asyncio.wait_for(plugin.poll(config, credential, target), timeout=timeout)

        retryer: AsyncRetrying = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, max=5),
            reraise=True,
        )
        try:
            async with self._semaphore:
                return await retryer(attempt)
        except Exception as exc:  # noqa: BLE001 - a failing target must never kill its loop
            return PollResult(success=False, error_message=str(exc))


@lru_cache
def get_supervisor() -> PollingSupervisor:
    return PollingSupervisor(get_databases(), get_metrics_writer())
