"""Destructive maintenance: wipe the inventory so discovery can start from scratch."""

from sqlalchemy import and_, delete, or_, select

from app.db.session import Databases
from app.domain.enums import DeviceType, EntityType
from app.domain.metrics_models import CheckResult, MetricRollup, MetricSample
from app.domain.models import (
    AlertEvent,
    AlertStateRow,
    Device,
    DeviceAddress,
    DiscoveredCandidate,
    Event,
    IntegrationTarget,
    Service,
)
from app.scheduler.supervisor import PollingSupervisor


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
