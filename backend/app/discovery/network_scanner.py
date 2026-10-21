import asyncio
import datetime
import ipaddress

from sqlalchemy import select

from app.background import spawn
from app.config import get_settings
from app.db.session import Databases
from app.discovery.auto_login import attempt_ssh_auto_login, attempt_wallet_login
from app.discovery.hostnames import RANK, clean
from app.discovery.scan_status import get_scan_status_registry
from app.discovery.service import DiscoveredServiceStore, DiscoveryService
from app.discovery.techniques import (
    arp,
    banner_grab,
    device_names,
    fingerprint,
    http_probe,
    icmp,
    nmap_scan,
    tcp_ports,
    tls_probe,
)
from app.domain.bootstrap import ensure_default_discovery_settings
from app.domain.models import Network
from app.logging_setup import get_logger

logger = get_logger(__name__)

MAX_HOSTS_PER_SCAN = 1024
SCAN_CONCURRENCY = 32
CANDIDATE_EXPIRY_DAYS = 30
_TLS_PORTS = {443, 8443, 8006, 8043, 8843, 5986}
# Bounds concurrent nmap processes across all scans so fingerprinting never
# starves the event loop or the box; each is a short-lived subprocess.
_NMAP_SEMAPHORE = asyncio.Semaphore(8)


async def _best_hostname(ip: str, dns_server: str | None) -> tuple[str | None, str | None]:
    """The most trustworthy name the network gives for this address (DNS, then mDNS, then NetBIOS)."""
    names = [(clean(name), source) for name, source in await device_names.lookup_names(ip, dns_server)]
    names = [(name, source) for name, source in names if name]
    if not names:
        return None, None
    name, source = min(names, key=lambda pair: RANK[pair[1]])
    return name, source


async def _fingerprint_and_store(
    databases: Databases, device_id: int, ip: str, ports: list[int], tuning: nmap_scan.NmapTuning
) -> None:
    """Runs after a host's ports are known open ("service is up"): one nmap -sV
    over those ports, written onto the matching Service rows. Runs as its own
    task so a slow host never delays the scan or any request."""
    async with _NMAP_SEMAPHORE:
        found = await nmap_scan.fingerprint_services(ip, ports, tuning)
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


_scanning_networks: set[int] = set()
_scanning_cidrs: set[str] = set()


async def scan_network(databases: Databases, network_id: int) -> None:
    # Claim the network before the first await, so two triggers (the schedule and a click, or a double
    # click) cannot both pass the check; the second returns immediately.
    if network_id in _scanning_networks:
        return
    _scanning_networks.add(network_id)
    try:
        async with databases.app_session_factory() as session:
            network = await session.get(Network, network_id)
            if network is None:
                return
            cidr = network.cidr
        status_registry = get_scan_status_registry()
        if status_registry.get(network_id).status == "scanning":
            return
        try:
            await scan_cidr(databases, cidr, network_id=network_id)
        except ValueError as exc:
            logger.warning(
                "invalid_or_oversized_network_cidr", network_id=network_id, cidr=cidr, error=str(exc)
            )
            status_registry.fail(network_id, str(exc))
    finally:
        _scanning_networks.discard(network_id)


async def scan_cidr(
    databases: Databases, cidr: str, *, network_id: int | None = None, max_hosts: int = MAX_HOSTS_PER_SCAN
) -> dict[str, object]:
    """Pings and port-probes every host in `cidr`, recording what answers through the usual
    discovery funnel (`DiscoveryService`). `network_id=None` is for a range that is not a registered
    `Network` - the AI Mode discoverer's ad hoc sweeps (see `agent_tools.discover_hosts`). Live scan
    progress (`scan_status`) and SSH auto-login are both keyed by a real Network (credential bindings
    are per-network), so both are skipped when `network_id` is None; wallet-credential auto-login
    (`attempt_wallet_login`, not tied to a network) still runs either way.

    Reentrancy for the `network_id=None` case is guarded here by `cidr` string, since there is no
    caller-side claim like `scan_network`'s `_scanning_networks` to rely on.
    """
    net = ipaddress.ip_network(cidr, strict=False)
    hosts = list(net.hosts())
    if len(hosts) > max_hosts:
        raise ValueError(f"{cidr} has {len(hosts)} hosts, more than the {max_hosts} limit")

    if network_id is None:
        if cidr in _scanning_cidrs:
            return {"hosts_scanned": 0, "hosts_up": [], "skipped": "already scanning this range"}
        _scanning_cidrs.add(cidr)

    status_registry = get_scan_status_registry()
    discovery_service = DiscoveryService(databases)
    service_store = DiscoveredServiceStore(databases)
    hosts_up: list[str] = []
    try:
        async with databases.app_session_factory() as session:
            discovery_settings = await ensure_default_discovery_settings(session)
            nmap_enabled = discovery_settings.nmap_enabled
            dns_server = discovery_settings.dns_server or None
            tuning = nmap_scan.NmapTuning(
                timing_template=discovery_settings.timing_template,
                host_timeout_seconds=discovery_settings.host_timeout_seconds,
                max_retries=discovery_settings.max_retries,
                version_intensity=discovery_settings.version_intensity,
            )
        arp_table = await arp.get_arp_table()
        semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)
        if network_id is not None:
            status_registry.start(network_id, len(hosts))

        async def scan_one(ip_str: str) -> None:
            async with semaphore:
                try:
                    await probe_host(ip_str)
                except Exception as exc:
                    # One bad host (a missing `ping`, a database error) must not abort the rest of the scan.
                    if network_id is not None:
                        status_registry.host_failed(network_id)
                    logger.warning("host_scan_failed", network_id=network_id, host=ip_str, error=repr(exc))
                finally:
                    if network_id is not None:
                        status_registry.advance(network_id)

        async def probe_host(ip_str: str) -> None:
            alive = await icmp.ping_host(ip_str)
            open_ports = await tcp_ports.scan_ports(ip_str)
            if not alive and not open_ports:
                return
            hosts_up.append(ip_str)

            nmap_result = None
            if open_ports and get_settings().nmap_os_detection_enabled:
                nmap_result = await nmap_scan.scan_host(ip_str)

            mac = arp_table.get(ip_str)
            hostname, hostname_source = await _best_hostname(ip_str, dns_server)
            device_id = await discovery_service.record_device_observation(
                network_id=network_id,
                ip=ip_str,
                mac=mac,
                hostname=hostname,
                hostname_source=hostname_source,
                open_ports=open_ports,
                via="network_scan",
                os_name=nmap_result.os_name if nmap_result else None,
                os_accuracy=nmap_result.os_accuracy if nmap_result else None,
            )

            if network_id is not None and 22 in open_ports:
                await attempt_ssh_auto_login(databases, network_id, ip_str, device_id)

            for port in open_ports:
                attributes: dict[str, object] = {}
                http_info = await http_probe.probe_http(ip_str, port)
                if http_info:
                    attributes["http"] = http_info
                suggestion = fingerprint.suggest_integration_type(port, http_info)
                if suggestion:
                    attributes["suggested_integration_type"] = suggestion
                    await attempt_wallet_login(databases, ip_str, device_id, port, suggestion)
                if port in _TLS_PORTS:
                    tls_info = await tls_probe.probe_tls(ip_str, port)
                    if tls_info:
                        attributes["tls"] = tls_info
                        await discovery_service.set_hostname(device_id, tls_info.get("common_name"), "tls")
                elif not http_info:
                    # Not a web/TLS port and nothing answered an HTTP GET -
                    # try a plain server-speaks-first banner read instead
                    # (SSH/FTP/SMTP/etc.). No nmap, no privileges needed.
                    banner = await banner_grab.grab_banner(ip_str, port)
                    if banner:
                        attributes["banner"] = banner
                if nmap_result and port in nmap_result.services:
                    attributes["nmap_service"] = nmap_result.services[port]

                protocol = "https" if port in _TLS_PORTS else ("http" if http_info else "tcp")
                banner_info = attributes.get("banner")
                await service_store.upsert(
                    device_id=device_id,
                    ip=ip_str,
                    port=port,
                    service_type=protocol,
                    source="scan",
                    fingerprint={"banner": banner_info, "source": "probe"} if banner_info else None,
                )
                await discovery_service.record_service_observation(
                    network_id=network_id,
                    ip=ip_str,
                    port=port,
                    protocol=protocol,
                    attributes=attributes,
                    via="network_scan",
                )

            if open_ports and nmap_enabled:
                spawn(
                    _fingerprint_and_store(databases, device_id, ip_str, open_ports, tuning),
                    f"nmap-fingerprint-{ip_str}",
                )

        try:
            await asyncio.gather(*(scan_one(str(ip)) for ip in hosts))
        except Exception as exc:
            if network_id is not None:
                status_registry.fail(network_id, repr(exc))
            raise
        finally:
            if network_id is not None:
                status_registry.finish(network_id)
    finally:
        if network_id is None:
            _scanning_cidrs.discard(cidr)

    return {"hosts_scanned": len(hosts), "hosts_up": hosts_up}


_last_auto_run: datetime.datetime | None = None
SCHEDULER_TICK_SECONDS = 60.0


async def run_scheduled_discovery(databases: Databases) -> None:
    """Ticks every minute; only scans when settings say scan_mode=auto and the
    configured interval has elapsed, so changing settings takes effect live."""
    global _last_auto_run
    async with databases.app_session_factory() as session:
        settings = await ensure_default_discovery_settings(session)
        mode, interval = settings.scan_mode, settings.auto_interval_seconds
    if mode != "auto":
        return
    now = datetime.datetime.now(datetime.UTC)
    if _last_auto_run is not None and (now - _last_auto_run).total_seconds() < interval:
        return
    _last_auto_run = now
    await run_discovery_for_all_networks(databases)


async def run_discovery_for_all_networks(databases: Databases) -> None:
    async with databases.app_session_factory() as session:
        result = await session.execute(select(Network.id))
        network_ids = [row[0] for row in result.all()]

    for network_id in network_ids:
        try:
            await scan_network(databases, network_id)
        except Exception as exc:
            # Keep going: one network failing must not stop the others or the cleanup below.
            logger.warning("network_scan_failed", network_id=network_id, error=repr(exc))

    expired = await DiscoveryService(databases).expire_stale(
        datetime.timedelta(days=CANDIDATE_EXPIRY_DAYS)
    )
    if expired:
        logger.info("discovery_candidates_expired", count=expired)
