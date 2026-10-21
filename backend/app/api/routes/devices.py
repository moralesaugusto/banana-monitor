import asyncio

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import AppSession, MetricsSession
from app.api.schemas.devices import (
    DeviceCreate,
    DeviceDetail,
    DeviceListRead,
    DeviceRead,
    DeviceUpdate,
    MetricPoint,
)
from app.db.session import get_databases
from app.discovery.oui import get_oui_registry
from app.discovery.rescan import RescanError, rescan_device
from app.domain.bootstrap import ensure_default_site
from app.domain.enums import CandidateType, EntityType, HealthStatus
from app.domain.models import Device, DiscoveredCandidate, IntegrationTarget, Service
from app.domain.roles import infer_role
from app.metrics.queries import get_latest_metric_values_for_entity, get_recent_metric_samples
from app.scheduler.supervisor import get_supervisor

router = APIRouter(prefix="/devices", tags=["devices"])


async def _get_or_404(session: AppSession, device_id: int) -> Device:
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


def _fingerprint_text(service: Service) -> str:
    return " ".join(str(v) for k, v in (service.fingerprint or {}).items() if k != "fingerprinted_at")


@router.get("", response_model=list[DeviceListRead])
async def list_devices(session: AppSession) -> list[DeviceListRead]:
    result = await session.execute(
        select(Device)
        .order_by(Device.display_name)
        .options(selectinload(Device.addresses), selectinload(Device.services), selectinload(Device.network))
    )
    oui_registry = get_oui_registry()
    reads = []
    for device in result.scalars().all():
        read = DeviceListRead.model_validate(device)
        addresses = sorted(device.addresses, key=lambda a: not a.is_primary)
        read.vendor = next(
            (v for v in (oui_registry.lookup(a.mac_address) for a in addresses) if v), None
        )
        read.network_name = device.network.name if device.network else None
        read.service_count = len(device.services)
        read.services_up = sum(1 for s in device.services if s.status is HealthStatus.UP)
        read.role = infer_role(device.device_type, [(s.port, _fingerprint_text(s)) for s in device.services])
        reads.append(read)
    return reads


@router.post("", response_model=DeviceRead, status_code=201)
async def create_device(payload: DeviceCreate, session: AppSession) -> Device:
    site_id = payload.site_id
    if site_id is None:
        site = await ensure_default_site(session)
        site_id = site.id

    device = Device(
        site_id=site_id,
        network_id=payload.network_id,
        hostname=payload.hostname or None,
        hostname_source="manual" if payload.hostname else None,
        display_name=payload.display_name,
        primary_ip=payload.primary_ip,
        device_type=payload.device_type,
        tags=payload.tags,
        notes=payload.notes,
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device


@router.get("/{device_id}", response_model=DeviceDetail)
async def get_device(device_id: int, session: AppSession, metrics_session: MetricsSession) -> DeviceDetail:
    result = await session.execute(
        select(Device)
        .where(Device.id == device_id)
        .options(selectinload(Device.addresses), selectinload(Device.services))
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    detail = DeviceDetail.model_validate(device)
    registry = get_oui_registry()
    for address in detail.addresses:
        address.vendor = registry.lookup(address.mac_address)
    detail.metrics = await get_latest_metric_values_for_entity(metrics_session, EntityType.DEVICE, device_id)
    return detail


@router.get("/{device_id}/metrics/{metric_name}", response_model=list[MetricPoint])
async def get_device_metric_history(
    device_id: int, metric_name: str, metrics_session: MetricsSession
) -> list[MetricPoint]:
    samples = await get_recent_metric_samples(metrics_session, EntityType.DEVICE, device_id, metric_name)
    return [MetricPoint(ts=ts, value=value) for ts, value in samples]


@router.patch("/{device_id}", response_model=DeviceRead)
async def update_device(device_id: int, payload: DeviceUpdate, session: AppSession) -> Device:
    device = await _get_or_404(session, device_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    await session.commit()
    await session.refresh(device)
    return device


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: int, session: AppSession) -> None:
    device = await _get_or_404(session, device_id)
    # SQLite does not enforce the device foreign keys (see decisions.md), so release the references
    # here. Services stay, unattached, and are re-linked by IP if the host is discovered again; the
    # device candidate goes so that rediscovery provisions a fresh device.
    await session.execute(update(Service).where(Service.device_id == device_id).values(device_id=None))
    await session.execute(
        update(IntegrationTarget).where(IntegrationTarget.device_id == device_id).values(device_id=None)
    )
    await session.execute(
        delete(DiscoveredCandidate).where(
            DiscoveredCandidate.candidate_type == CandidateType.DEVICE,
            DiscoveredCandidate.resulting_device_id == device_id,
        )
    )
    await session.execute(
        update(DiscoveredCandidate)
        .where(DiscoveredCandidate.resulting_device_id == device_id)
        .values(resulting_device_id=None)
    )
    await session.delete(device)
    await session.commit()


@router.post("/{device_id}/rescan")
async def rescan_device_services(device_id: int, session: AppSession) -> dict[str, int]:
    """Re-detects open ports and fingerprints them with nmap; waits for the result."""
    if await session.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        updated = await rescan_device(get_databases(), device_id)
    except RescanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Refresh the status of the device's monitored services too, so the result matches what was just found.
    monitored = select(Service.id).where(Service.device_id == device_id, Service.managed.is_(True))
    service_ids = list(await session.scalars(monitored))
    supervisor = get_supervisor()
    await asyncio.gather(*(supervisor.check_service_now(service_id) for service_id in service_ids))
    return {"updated": updated}
