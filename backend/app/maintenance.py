"""Destructive maintenance: start the whole installation from scratch."""

from sqlalchemy import and_, delete, or_, select

from app.db.session import Databases
from app.domain.bootstrap import (
    ensure_default_agents,
    ensure_default_assistant_config,
    ensure_default_discovery_settings,
    ensure_default_site,
)
from app.domain.enums import DeviceType, EntityType
from app.domain.metrics_models import CheckResult, MetricRollup, MetricSample, MetricsBase
from app.domain.models import (
    AlertEvent,
    AlertStateRow,
    Base,
    Device,
    DeviceAddress,
    DiscoveredCandidate,
    Event,
    Integration,
    IntegrationTarget,
    Service,
)
from app.knowledge.models import KnowledgeBase, KnowledgeCollection
from app.knowledge.qdrant_store import delete_collection as qdrant_delete_collection
from app.knowledge.qdrant_store import get_qdrant_client
from app.knowledge.service import ensure_default_knowledge_collections, qdrant_key
from app.scheduler.supervisor import PollingSupervisor
from app.selfhealth.monitor import ensure_self_health_device

KEPT_TABLES = frozenset({"admin_users", "auth_sessions", "login_attempts", "audit_log", "alembic_version"})
"""What a full reset leaves in app.db: the administrator's login and sessions (so the person who pressed the
button is not locked out) and the audit log. Stored credentials live in credentials.db and are not touched."""


async def reset_inventory(databases: Databases, supervisor: PollingSupervisor) -> dict[str, int]:
    """Deletes every device (except the platform's own), service, discovery candidate and their
    history. Networks, integrations, credentials, alert rules and settings are kept."""
    async with databases.app_session_factory() as session:
        self_ids = list(
            await session.scalars(select(Device.id).where(Device.device_type == DeviceType.PLATFORM_SELF))
        )
        service_ids = list(await session.scalars(select(Service.id)))
        for service_id in service_ids:
            supervisor.remove_target(service_id)

        device_filter = Device.id.not_in(self_ids) if self_ids else Device.id.is_not(None)
        device_ids = list(await session.scalars(select(Device.id).where(device_filter)))

        state_ids = select(AlertStateRow.id).where(
            or_(
                AlertStateRow.entity_type == EntityType.SERVICE,
                and_(AlertStateRow.entity_type == EntityType.DEVICE, AlertStateRow.entity_id.in_(device_ids)),
            )
        )
        await session.execute(delete(AlertEvent).where(AlertEvent.alert_state_id.in_(state_ids)))
        await session.execute(delete(AlertStateRow).where(AlertStateRow.id.in_(state_ids)))
        event_type, event_id = Event.related_entity_type, Event.related_entity_id
        await session.execute(
            delete(Event).where(
                or_(
                    event_type == EntityType.SERVICE,
                    and_(event_type == EntityType.DEVICE, event_id.in_(device_ids)),
                )
            )
        )
        await session.execute(delete(IntegrationTarget))
        await session.execute(delete(Service))
        await session.execute(delete(DeviceAddress).where(DeviceAddress.device_id.in_(device_ids)))
        await session.execute(delete(Device).where(Device.id.in_(device_ids)))
        await session.execute(delete(DiscoveredCandidate))
        await session.commit()

    async with databases.metrics_session_factory() as session:
        for model in (CheckResult, MetricSample, MetricRollup):
            await session.execute(
                delete(model).where(
                    or_(
                        model.entity_type == EntityType.SERVICE,
                        and_(model.entity_type == EntityType.DEVICE, model.entity_id.in_(device_ids)),
                    )
                )
            )
        await session.commit()

    return {"devices": len(device_ids), "services": len(service_ids)}


async def reset_everything(databases: Databases, supervisor: PollingSupervisor) -> dict[str, int]:
    """Start from scratch: every table in app.db except KEPT_TABLES, all metrics, and the whole knowledge
    base (entries, vectors and collections) are emptied, then the first-start defaults are seeded again
    exactly as on a fresh install. Kept: the administrator's login, the audit log, and stored
    credentials with the master key (credentials.db is not touched)."""
    async with databases.app_session_factory() as session:
        service_ids = list(await session.scalars(select(Service.id)))
        integration_ids = list(await session.scalars(select(Integration.id)))
        own_device = Device.device_type != DeviceType.PLATFORM_SELF
        device_count = len(list(await session.scalars(select(Device.id).where(own_device))))
    for service_id in service_ids:
        supervisor.remove_target(service_id)
    for integration_id in integration_ids:
        supervisor.remove_integration(integration_id)

    async with databases.app_session_factory() as session:
        # Foreign keys are not enforced on pooled connections, so children go first explicitly.
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in KEPT_TABLES:
                await session.execute(delete(table))
        await session.commit()

    async with databases.metrics_session_factory() as session:
        for table in reversed(MetricsBase.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()

    async with databases.knowledge_session_factory() as session:
        collections = list(await session.scalars(select(KnowledgeCollection)))
        for collection in collections:
            await qdrant_delete_collection(get_qdrant_client(), qdrant_key(collection.id))
        for table in reversed(KnowledgeBase.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()

    async with databases.app_session_factory() as session:
        await ensure_default_site(session)
        await ensure_default_assistant_config(session)
        await ensure_default_discovery_settings(session)
        await ensure_default_agents(session)
    await ensure_default_knowledge_collections(databases)
    await ensure_self_health_device(databases)
    return {"devices": device_count, "services": len(service_ids)}
