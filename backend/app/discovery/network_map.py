"""Builds the per-address view backing the Networks page's map - see
docs/decisions.md's "Network map address cap" entry. Reuses the same CIDR
expansion and host-count cap as `network_scanner.py`'s live scan (a /22 at
most), since the same "don't render thousands of DOM nodes" argument applies
to the frontend's SVG grid; above the cap this returns status counts instead
of one row per address."""

import ipaddress
from typing import Any

from sqlalchemy import select

from app.db.session import Databases
from app.discovery.network_scanner import MAX_HOSTS_PER_SCAN
from app.domain.enums import HealthStatus
from app.domain.models import Device, DeviceAddress, Network


async def build_network_map(databases: Databases, network: Network) -> dict[str, Any]:
    net = ipaddress.ip_network(network.cidr, strict=False)
    hosts = list(net.hosts())
    total = len(hosts)

    if total > MAX_HOSTS_PER_SCAN:
        summary = await _status_summary(databases, network.id)
        return {
            "network_id": network.id,
            "cidr": network.cidr,
            "total_addresses": total,
            "truncated": True,
            "addresses": [],
            "summary": summary,
        }

    async with databases.app_session_factory() as session:
        result = await session.execute(
            select(DeviceAddress.ip_address, Device)
            .join(Device, Device.id == DeviceAddress.device_id)
            .where(Device.network_id == network.id)
        )
        device_by_ip = {ip: device for ip, device in result.all()}

    addresses = [_address_cell(str(host), device_by_ip.get(str(host))) for host in hosts]
    return {
        "network_id": network.id,
        "cidr": network.cidr,
        "total_addresses": total,
        "truncated": False,
        "addresses": addresses,
        "summary": None,
    }


def _address_cell(ip: str, device: Device | None) -> dict[str, Any]:
    if device is None:
        return {"ip": ip, "status": None, "device_id": None, "display_name": None, "managed": None}
    return {
        "ip": ip,
        "status": device.status,
        "device_id": device.id,
        "display_name": device.display_name,
        "managed": device.managed,
    }


async def _status_summary(databases: Databases, network_id: int) -> dict[str, int]:
    summary: dict[str, int] = {status.value: 0 for status in HealthStatus}
    summary["unmanaged"] = 0
    async with databases.app_session_factory() as session:
        result = await session.execute(select(Device).where(Device.network_id == network_id))
        for device in result.scalars().all():
            key = "unmanaged" if not device.managed else device.status.value
            summary[key] = summary.get(key, 0) + 1
    return summary
