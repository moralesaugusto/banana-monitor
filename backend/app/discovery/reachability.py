"""Derives status for devices nothing else polls (scan-discovered and manually added hosts).

Ping answers -> UP. Ping silent but a known service port still accepts a
connection -> DEGRADED (shown as "partial"). Neither -> DOWN. Integration-backed
device types (linux, proxmox) keep the status written by their poll.
"""

import asyncio
import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import Databases
from app.discovery.techniques.icmp import ping_host
from app.discovery.techniques.tcp_ports import scan_ports
from app.domain.enums import DeviceType, HealthStatus
from app.domain.models import Device, Integration, IntegrationTarget, utcnow

REACHABILITY_INTERVAL_SECONDS = 60.0
_UNPOLLED_TYPES = {DeviceType.OTHER, DeviceType.WINDOWS, DeviceType.NETWORK_EQUIPMENT}
_CONCURRENCY = asyncio.Semaphore(16)

INACTIVE_AFTER = datetime.timedelta(days=3)
"""How long a device may stay DOWN (never confirmed reachable, or not confirmed reachable since this
long ago) before it counts as "inactive" - old and gone, not just a transient blip - rather than
merely "down" (which a single missed check already reports). Inactive devices are excluded from AI
Mode's automatic target selection (schedule.py's next_targets) so nothing keeps trying to discover,
inspect or act on a host nothing has found in days; they stay visible and still get the regular
reachability/poll check every cycle, so one still coming back online clears the flag on its own."""


def device_is_inactive(
    status: HealthStatus, last_seen_at: datetime.datetime | None, *, now: datetime.datetime | None = None
) -> bool:
    """A device counts as inactive once it has been DOWN and unseen for `INACTIVE_AFTER` - never just
    from a momentary blip, and never while any status other than DOWN (an UP/DEGRADED/unknown device,
    even an integration-polled one between its own poll cycles, is never inactive)."""
    if status is not HealthStatus.DOWN:
        return False
    if last_seen_at is None:
        return True
    return (now or utcnow()) - last_seen_at > INACTIVE_AFTER


async def probe_device(ip: str, service_ports: list[int]) -> HealthStatus:
    async with _CONCURRENCY:
        if await ping_host(ip):
            return HealthStatus.UP
        if service_ports and await scan_ports(ip, service_ports):
            return HealthStatus.DEGRADED
        return HealthStatus.DOWN


async def _integration_polled_device_ids(session: AsyncSession) -> set[int]:
    """Devices an integration already polls (and writes the status of), whatever their type says."""
    targets = select(IntegrationTarget.device_id).where(IntegrationTarget.device_id.is_not(None))
    ids = {device_id for device_id in await session.scalars(targets) if device_id is not None}
    for config in await session.scalars(select(Integration.config).where(Integration.enabled.is_(True))):
        device_id = (config or {}).get("device_id")
        if isinstance(device_id, int):
            ids.add(device_id)
    return ids


async def run_reachability(databases: Databases) -> None:
    async with databases.app_session_factory() as session:
        polled = await _integration_polled_device_ids(session)
        devices = [
            device
            for device in (
                await session.scalars(
                    select(Device)
                    .where(Device.primary_ip.is_not(None), Device.device_type.in_(_UNPOLLED_TYPES))
                    .options(selectinload(Device.services))
                )
            ).all()
            if device.id not in polled
        ]
        targets = {
            device.id: (
                device.primary_ip,
                sorted({s.port for s in device.services if s.port is not None}),
            )
            for device in devices
        }

    results = await asyncio.gather(*(probe_device(ip, ports) for ip, ports in targets.values()))  # type: ignore[arg-type]

    async with databases.app_session_factory() as session:
        for device_id, status in zip(targets, results, strict=True):
            device = await session.get(Device, device_id)
            if device is None:
                continue
            device.status = status
            if status is not HealthStatus.DOWN:
                device.last_seen_at = utcnow()
        await session.commit()
