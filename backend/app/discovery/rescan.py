"""On-demand scanning of one device (every TCP port) or one service (just its port), fingerprinted with
nmap and awaited so the UI gets the result."""

from sqlalchemy import select

from app.db.session import Databases
from app.discovery.service import DiscoveredServiceStore, DiscoveryService
from app.discovery.techniques import device_names, nmap_scan, tcp_ports
from app.domain.bootstrap import ensure_default_discovery_settings
from app.domain.models import Device, Service


class RescanError(Exception):
    pass


async def rescan_device(databases: Databases, device_id: int, only_port: int | None = None) -> int:
    """Scans the whole host (every TCP port) and fingerprints what is open, or just `only_port` when given.
    Returns services updated."""
    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        if device is None or not device.primary_ip:
            raise RescanError("Device has no IP address to scan")
        ip = device.primary_ip
        settings = await ensure_default_discovery_settings(session)
        dns_server = settings.dns_server or None
        if not settings.nmap_enabled:
            raise RescanError("nmap fingerprinting is disabled in Settings")
        tuning = nmap_scan.NmapTuning(
            timing_template=settings.timing_template,
            host_timeout_seconds=settings.host_timeout_seconds,
            max_retries=settings.max_retries,
            version_intensity=settings.version_intensity,
        )
        known = list(
            await session.scalars(
                select(Service.port).where(Service.device_id == device_id, Service.port.is_not(None))
            )
        )

    # The whole-host scan also asks the network for the device's name (DNS, mDNS, NetBIOS).
    if only_port is None:
        for name, source in await device_names.lookup_names(ip, dns_server):
            await DiscoveryService(databases).set_hostname(device_id, name, source)

    candidates = (
        [only_port]
        if only_port is not None
        else sorted({*tcp_ports.ALL_PORTS, *(p for p in known if p is not None)})
    )
    open_ports = await tcp_ports.scan_ports(ip, candidates)
    if not open_ports:
        return 0
    found = await nmap_scan.fingerprint_services(ip, open_ports, tuning)
    store = DiscoveredServiceStore(databases)
    for port, info in found.items():
        await store.upsert(
            device_id=device_id,
            ip=ip,
            port=port,
            service_type=nmap_scan.service_type_for(info, port),
            source="scan",
            fingerprint={**info, "source": "nmap"},
        )
    return len(found)
