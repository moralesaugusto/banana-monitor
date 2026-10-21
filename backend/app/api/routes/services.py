from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from sqlalchemy import String, or_, select

from app.api.deps import AppSession, MetricsSession
from app.api.schemas.services import ServiceBulkAction, ServiceCreate, ServiceRead, ServiceUpdate
from app.db.session import get_databases
from app.discovery.oui import get_oui_registry
from app.discovery.rescan import RescanError, rescan_device
from app.domain.enums import EntityType, HealthStatus, ServiceType
from app.domain.models import Device, DeviceAddress, Service
from app.integrations import registry
from app.metrics.queries import get_latest_metric_values
from app.scheduler.supervisor import SERVICE_TYPE_TO_PLUGIN, get_supervisor

router = APIRouter(prefix="/services", tags=["services"])


async def _get_or_404(session: AppSession, service_id: int) -> Service:
    service = await session.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


async def _validate_config(service_type: ServiceType, config: dict[str, object]) -> None:
    plugin_key = SERVICE_TYPE_TO_PLUGIN.get(service_type)
    if plugin_key is None:
        return
    plugin = registry.get_plugin(plugin_key)
    if plugin is None:
        return
    result = await plugin.validate_config(config, None)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.message or "Invalid service config")


async def _device_vendors(session: AppSession, device_ids: list[int]) -> dict[int, str | None]:
    """One vendor guess per device id: its primary address's MAC if it has
    one, else its first address's - looked up against the IEEE OUI registry
    (see `app.discovery.oui`)."""
    if not device_ids:
        return {}
    result = await session.execute(
        select(DeviceAddress)
        .where(DeviceAddress.device_id.in_(device_ids))
        .order_by(DeviceAddress.device_id, DeviceAddress.is_primary.desc())
    )
    oui_registry = get_oui_registry()
    vendors: dict[int, str | None] = {}
    for address in result.scalars().all():
        if address.device_id not in vendors:
            vendors[address.device_id] = oui_registry.lookup(address.mac_address)
    return vendors


async def _with_latency(
    services: list[Service], session: AppSession, metrics_session: MetricsSession
) -> list[ServiceRead]:
    latencies = await get_latest_metric_values(
        metrics_session, EntityType.SERVICE, "latency_ms", [s.id for s in services]
    )
    device_ids = [s.device_id for s in services if s.device_id is not None]
    vendors = await _device_vendors(session, device_ids)

    reads = []
    for service in services:
        read = ServiceRead.model_validate(service)
        read.last_latency_ms = latencies.get(service.id)
        read.device_vendor = vendors.get(service.device_id) if service.device_id is not None else None
        reads.append(read)
    return reads


SortKey = Literal["name", "type", "device", "port", "status", "latency", "last_checked", "vendor"]


def _sort_value(read: ServiceRead, device_names: dict[int, str], key: SortKey) -> tuple[bool, Any]:
    """None-safe sort keys; missing values sort last in ascending order."""
    value: Any
    if key == "name":
        value = read.name.lower()
    elif key == "type":
        value = read.service_type.value
    elif key == "device":
        value = device_names.get(read.device_id, "").lower() if read.device_id is not None else None
    elif key == "port":
        value = read.port
    elif key == "status":
        value = read.status.value
    elif key == "latency":
        value = read.last_latency_ms
    elif key == "vendor":
        value = (read.device_vendor or "").lower() or None
    else:
        value = read.last_checked_at
    return (value is None, value if value is not None else 0)


@router.get("", response_model=list[ServiceRead])
async def list_services(
    session: AppSession,
    metrics_session: MetricsSession,
    status: HealthStatus | None = None,
    service_type: ServiceType | None = None,
    managed: bool | None = None,
    source: str | None = None,
    device_id: int | None = None,
    q: str | None = None,
    sort: SortKey = "name",
    order: Literal["asc", "desc"] = "asc",
) -> list[ServiceRead]:
    query = select(Service)
    if status is not None:
        query = query.where(Service.status == status)
    if service_type is not None:
        query = query.where(Service.service_type == service_type)
    if managed is not None:
        query = query.where(Service.managed.is_(managed))
    if source is not None:
        query = query.where(Service.source == source)
    if device_id is not None:
        query = query.where(Service.device_id == device_id)
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                Service.name.ilike(like),
                Service.fingerprint.cast(String).ilike(like),
                Service.device_id.in_(select(Device.id).where(Device.display_name.ilike(like))),
            )
        )
    result = await session.execute(query)
    reads = await _with_latency(list(result.scalars().all()), session, metrics_session)

    device_ids = {r.device_id for r in reads if r.device_id is not None}
    device_names: dict[int, str] = {}
    if device_ids:
        names = await session.execute(select(Device.id, Device.display_name).where(Device.id.in_(device_ids)))
        device_names = {i: n for i, n in names.all()}
    # Sort in Python: latency/vendor are not columns, and the list is small (homelab scale).
    reads.sort(key=lambda r: _sort_value(r, device_names, sort), reverse=order == "desc")
    return reads


@router.post("/bulk")
async def bulk_action(payload: ServiceBulkAction, session: AppSession) -> dict[str, int]:
    """Applies one action to many services (the Services page's multi-select).
    Unknown ids are skipped; the count of rows actually changed is returned."""
    result = await session.execute(select(Service).where(Service.id.in_(payload.ids)))
    services = list(result.scalars().all())
    supervisor = get_supervisor()
    for service in services:
        if payload.action == "delete":
            await session.delete(service)
        else:
            service.managed = payload.action == "monitor"
    await session.commit()

    for service in services:
        if payload.action == "delete":
            supervisor.remove_target(service.id)
        else:
            supervisor.reload_target(service)
    return {"affected": len(services)}


@router.post("", response_model=ServiceRead, status_code=201)
async def create_service(payload: ServiceCreate, session: AppSession) -> ServiceRead:
    await _validate_config(payload.service_type, payload.config)

    service = Service(
        device_id=payload.device_id,
        name=payload.name,
        service_type=payload.service_type,
        config=payload.config,
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)

    get_supervisor().add_target(service)

    read = ServiceRead.model_validate(service)
    if service.device_id is not None:
        vendors = await _device_vendors(session, [service.device_id])
        read.device_vendor = vendors.get(service.device_id)
    return read


@router.get("/{service_id}", response_model=ServiceRead)
async def get_service(service_id: int, session: AppSession, metrics_session: MetricsSession) -> ServiceRead:
    service = await _get_or_404(session, service_id)
    return (await _with_latency([service], session, metrics_session))[0]


@router.patch("/{service_id}", response_model=ServiceRead)
async def update_service(service_id: int, payload: ServiceUpdate, session: AppSession) -> Service:
    service = await _get_or_404(session, service_id)

    updates = payload.model_dump(exclude_unset=True)
    if "config" in updates:
        await _validate_config(updates.get("service_type", service.service_type), updates["config"])

    for field, value in updates.items():
        setattr(service, field, value)
    await session.commit()
    await session.refresh(service)

    get_supervisor().reload_target(service)
    return service


@router.delete("/{service_id}", status_code=204)
async def delete_service(service_id: int, session: AppSession) -> None:
    service = await _get_or_404(session, service_id)
    await session.delete(service)
    await session.commit()

    get_supervisor().remove_target(service_id)


@router.post("/{service_id}/rescan")
async def rescan_service(service_id: int, session: AppSession) -> dict[str, int | str | None]:
    service = await _get_or_404(session, service_id)
    if service.device_id is None or service.port is None:
        raise HTTPException(status_code=409, detail="Service has no device or port to fingerprint")
    try:
        updated = await rescan_device(get_databases(), service.device_id, only_port=service.port)
    except RescanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Re-fingerprinting says what the service is; check it again too, so its status is current.
    status = await get_supervisor().check_service_now(service_id)
    return {"updated": updated, "status": status.value if status else None}
