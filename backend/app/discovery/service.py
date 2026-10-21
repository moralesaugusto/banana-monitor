import datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.background import named_lock
from app.db.session import Databases
from app.discovery.hostnames import apply_hostname, clean
from app.discovery.oui import get_oui_registry
from app.domain.bootstrap import ensure_default_discovery_settings, ensure_default_site
from app.domain.enums import CandidateStatus, CandidateType, DeviceType, EntityType, ServiceType
from app.domain.models import (
    AlertEvent,
    AlertStateRow,
    Device,
    DeviceAddress,
    DiscoveredCandidate,
    IntegrationTarget,
    Service,
    utcnow,
)


class CandidateNotFoundError(LookupError):
    pass


class CandidateStateError(RuntimeError):
    """The candidate has already been accepted or ignored, so it cannot be accepted again."""


def _device_type_from_os(os_name: str | None) -> DeviceType:
    """A best-effort nmap -O guess is only confident enough to distinguish
    Windows from everything else - it's not asked to tell a NAS from a
    router from a generic Linux box, so anything that isn't clearly Windows
    stays OTHER (SSH auto-login, separately, promotes a host to LINUX once
    it actually authenticates - a much stronger signal than OS fingerprint
    text)."""
    if os_name and "windows" in os_name.lower():
        return DeviceType.WINDOWS
    return DeviceType.OTHER


class DiscoveryService:
    def __init__(self, databases: Databases) -> None:
        self._databases = databases

    async def record_device_observation(
        self,
        *,
        network_id: int | None,
        ip: str,
        mac: str | None,
        hostname: str | None,
        open_ports: list[int],
        via: str,
        os_name: str | None = None,
        os_accuracy: int | None = None,
        hostname_source: str | None = None,
    ) -> int:
        """Records the observation and, for a never-seen-before host, immediately
        provisions a real (unmanaged) Device from it - see docs/decisions.md
        "Auto-populate discovered devices". Re-observations of an
        already-provisioned host just refresh last_seen_at/attributes; nothing
        here creates a second Device for the same fingerprint. Returns the
        resulting (new or existing) Device id, so callers (e.g. the network
        scanner's auto-login path) can act on it without a second lookup.

        `os_name`/`os_accuracy` are an optional best-effort guess (currently
        from `nmap -O`, see techniques/nmap_scan.py) - only used to pick a
        DeviceType on first provisioning, never to override a device's type
        on a later re-observation (a noisy guess should never silently
        reclassify a device a human, or SSH auto-login, already typed)."""
        fingerprint = mac or ip
        vendor = get_oui_registry().lookup(mac)
        attributes = {
            "ip": ip,
            "mac": mac,
            "hostname": hostname,
            "hostname_source": hostname_source,
            "open_ports": open_ports,
            "vendor": vendor,
            "os_name": os_name,
            "os_accuracy": os_accuracy,
        }
        return await self._record_device(fingerprint, network_id, via, attributes)

    async def record_service_observation(
        self,
        *,
        network_id: int | None,
        ip: str,
        port: int,
        protocol: str,
        attributes: dict[str, Any],
        via: str,
    ) -> None:
        fingerprint = f"{ip}:{port}:{protocol}"
        payload = {"ip": ip, "port": port, "protocol": protocol, **attributes}
        await self._record(CandidateType.SERVICE, fingerprint, network_id, via, payload)
        await self._auto_accept_service(fingerprint, payload)

    async def _auto_accept_service(self, fingerprint: str, attrs: dict[str, Any]) -> None:
        """With `auto_accept_services` on, a pending service candidate becomes a monitored Service
        right away, with the same type and config the Discovery page pre-selects."""
        async with self._databases.app_session_factory() as session:
            if not (await ensure_default_discovery_settings(session)).auto_accept_services:
                return
            candidate_id = await session.scalar(
                select(DiscoveredCandidate.id).where(
                    DiscoveredCandidate.candidate_type == CandidateType.SERVICE,
                    DiscoveredCandidate.fingerprint == fingerprint,
                    DiscoveredCandidate.status == CandidateStatus.PENDING,
                )
            )
        if candidate_id is None:
            return
        protocol = attrs.get("protocol")
        service_type = {"https": ServiceType.HTTPS, "http": ServiceType.HTTP}.get(
            str(protocol), ServiceType.TCP
        )
        config = (
            {"host": attrs["ip"], "port": attrs["port"]}
            if service_type == ServiceType.TCP
            else {"url": f"{service_type.value}://{attrs['ip']}:{attrs['port']}"}
        )
        service = await self.accept_service(candidate_id, service_type, None, None, config)
        from app.scheduler.supervisor import get_supervisor  # local import: avoid a circular import

        get_supervisor().add_target(service)

    async def _record(
        self,
        candidate_type: CandidateType,
        fingerprint: str,
        network_id: int | None,
        via: str,
        attributes: dict[str, Any],
    ) -> None:
        async with self._databases.app_session_factory() as session:
            result = await session.execute(
                select(DiscoveredCandidate).where(
                    DiscoveredCandidate.candidate_type == candidate_type,
                    DiscoveredCandidate.fingerprint == fingerprint,
                )
            )
            existing = result.scalar_one_or_none()
            now = utcnow()

            if existing is not None:
                existing.last_seen_at = now
                existing.times_seen += 1
                existing.raw_attributes = attributes
                if existing.status == CandidateStatus.EXPIRED:
                    existing.status = CandidateStatus.PENDING
                await session.commit()
                return

            session.add(
                DiscoveredCandidate(
                    candidate_type=candidate_type,
                    fingerprint=fingerprint,
                    discovered_via=via,
                    network_id=network_id,
                    raw_attributes=attributes,
                    first_seen_at=now,
                    last_seen_at=now,
                    times_seen=1,
                    status=CandidateStatus.PENDING,
                )
            )
            await session.commit()

    async def _record_device(
        self,
        fingerprint: str,
        network_id: int | None,
        via: str,
        attributes: dict[str, Any],
    ) -> int:
        """Like `_record`, but for devices: a brand-new fingerprint is immediately
        provisioned as a real (unmanaged) Device rather than left `pending` -
        see docs/decisions.md. An already-known fingerprint just refreshes the
        observation and the linked Device's `last_seen_at`."""
        async with named_lock("device-observation"), self._databases.app_session_factory() as session:
            result = await session.execute(
                select(DiscoveredCandidate).where(
                    DiscoveredCandidate.candidate_type == CandidateType.DEVICE,
                    DiscoveredCandidate.fingerprint == fingerprint,
                )
            )
            existing = result.scalar_one_or_none()
            now = utcnow()
            if existing is None:
                existing = await self._match_known_address(session, attributes)

            if existing is not None:
                existing.last_seen_at = now
                existing.times_seen += 1
                existing.raw_attributes = attributes
                known = (
                    await session.get(Device, existing.resulting_device_id)
                    if existing.resulting_device_id is not None
                    else None
                )
                if known is None:
                    # Either a legacy candidate from before devices auto-populated, or its device was
                    # deleted: in both cases the host has no Device, so every service found on it would
                    # be orphaned. Provision one.
                    device = await self._provision_device(session, network_id, attributes, now)
                    existing.resulting_device_id = device.id
                    existing.status = CandidateStatus.ACCEPTED
                else:
                    known.last_seen_at = now
                    apply_hostname(known, attributes.get("hostname"), attributes.get("hostname_source"))
                await session.commit()
                assert existing.resulting_device_id is not None
                return existing.resulting_device_id

            device = await self._provision_device(session, network_id, attributes, now)
            session.add(
                DiscoveredCandidate(
                    candidate_type=CandidateType.DEVICE,
                    fingerprint=fingerprint,
                    discovered_via=via,
                    network_id=network_id,
                    raw_attributes=attributes,
                    first_seen_at=now,
                    last_seen_at=now,
                    times_seen=1,
                    status=CandidateStatus.ACCEPTED,
                    resulting_device_id=device.id,
                )
            )
            await session.commit()
            return device.id

    async def _match_known_address(
        self, session: AsyncSession, attributes: dict[str, Any]
    ) -> DiscoveredCandidate | None:
        """A host is fingerprinted by MAC, or by IP when no MAC was available. The same host can be seen
        with a MAC one scan and without the next (ARP not populated yet), which would look like a new
        device. So when the fingerprint is unknown, look for a device that already owns this IP.

        A different MAC on a known IP is a different piece of hardware that was handed the address
        (DHCP), so it is not merged. When a MAC shows up for an IP-fingerprinted device, the device
        learns it and is fingerprinted by MAC from then on."""
        ip, mac = attributes.get("ip"), attributes.get("mac")
        if not ip:
            return None
        address = (
            await session.scalars(
                select(DeviceAddress)
                .where(DeviceAddress.ip_address == ip)
                .order_by(DeviceAddress.is_primary.desc(), DeviceAddress.id)
            )
        ).first()
        if address is None:
            return None
        if mac and address.mac_address and address.mac_address.lower() != mac.lower():
            return None
        candidate = await session.scalar(
            select(DiscoveredCandidate).where(
                DiscoveredCandidate.candidate_type == CandidateType.DEVICE,
                DiscoveredCandidate.resulting_device_id == address.device_id,
            )
        )
        if candidate is None:
            return None
        previous = candidate.raw_attributes or {}
        if mac:
            address.mac_address = address.mac_address or mac
            candidate.fingerprint = mac
        else:
            # Seen without a MAC this time: keep what we already know rather than forgetting it.
            attributes["mac"] = previous.get("mac")
            attributes["vendor"] = attributes.get("vendor") or previous.get("vendor")
        return candidate

    async def merge_duplicate_devices(self) -> int:
        """One-off clean-up for devices the matching above would have prevented: several devices with the
        same primary IP (and at most one distinct MAC between them) are merged into one. A managed device
        wins over scan-created ones, otherwise the oldest. Services, addresses, candidates and integration
        targets move to the survivor. Groups with conflicting MACs are left alone. Returns devices removed."""
        removed = 0
        async with self._databases.app_session_factory() as session:
            query = select(Device).where(Device.primary_ip.is_not(None)).order_by(Device.id)
            devices = (await session.scalars(query)).all()
            groups: dict[str, list[Device]] = {}
            for device in devices:
                groups.setdefault(str(device.primary_ip), []).append(device)
            for group in (g for g in groups.values() if len(g) > 1):
                ids = [d.id for d in group]
                addresses = (
                    await session.scalars(select(DeviceAddress).where(DeviceAddress.device_id.in_(ids)))
                ).all()
                macs = {a.mac_address.lower() for a in addresses if a.mac_address}
                managed = [d for d in group if d.managed]
                if len(macs) > 1 or len(managed) > 1:
                    continue
                keeper = managed[0] if managed else group[0]
                for dup in (d for d in group if d.id != keeper.id):
                    await self._merge_into(session, keeper, dup)
                    removed += 1
            await session.commit()
        return removed

    async def _addresses(self, session: AsyncSession, device_id: int) -> list[DeviceAddress]:
        result = await session.scalars(select(DeviceAddress).where(DeviceAddress.device_id == device_id))
        return list(result.all())

    async def _merge_into(self, session: AsyncSession, keeper: Device, dup: Device) -> None:
        kept_addresses = {
            a.ip_address: a
            for a in await self._addresses(session, keeper.id)
        }
        for address in await self._addresses(session, dup.id):
            twin = kept_addresses.get(address.ip_address)
            if twin is None:
                address.device_id = keeper.id
            else:
                twin.mac_address = twin.mac_address or address.mac_address
                await session.delete(address)
        for model, column in (
            (Service, Service.device_id),
            (DiscoveredCandidate, DiscoveredCandidate.resulting_device_id),
            (IntegrationTarget, IntegrationTarget.device_id),
        ):
            for row in (await session.scalars(select(model).where(column == dup.id))).all():
                setattr(row, column.key, keeper.id)
        state_ids = select(AlertStateRow.id).where(
            AlertStateRow.entity_type == EntityType.DEVICE, AlertStateRow.entity_id == dup.id
        )
        await session.execute(delete(AlertEvent).where(AlertEvent.alert_state_id.in_(state_ids)))
        await session.execute(
            delete(AlertStateRow).where(
                AlertStateRow.entity_type == EntityType.DEVICE, AlertStateRow.entity_id == dup.id
            )
        )
        if dup.last_seen_at and (keeper.last_seen_at is None or dup.last_seen_at > keeper.last_seen_at):
            keeper.last_seen_at = dup.last_seen_at
        await session.flush()
        await session.delete(dup)

    async def _provision_device(
        self,
        session: AsyncSession,
        network_id: int | None,
        attributes: dict[str, Any],
        now: datetime.datetime,
    ) -> Device:
        site = await ensure_default_site(session)
        device = Device(
            site_id=site.id,
            network_id=network_id,
            hostname=clean(attributes.get("hostname")),
            hostname_source=attributes.get("hostname_source") if clean(attributes.get("hostname")) else None,
            display_name=clean(attributes.get("hostname")) or attributes.get("ip") or "Unnamed device",
            primary_ip=attributes.get("ip"),
            device_type=_device_type_from_os(attributes.get("os_name")),
            managed=False,
            last_seen_at=now,
        )
        session.add(device)
        await session.flush()

        if attributes.get("ip"):
            session.add(
                DeviceAddress(
                    device_id=device.id,
                    ip_address=attributes["ip"],
                    mac_address=attributes.get("mac"),
                    is_primary=True,
                )
            )
        return device

    async def _certificate_is_shared(self, session: AsyncSession, device: Device, name: str | None) -> bool:
        """Whether another host presents a certificate with this same name. A name shared like that (a vendor
        default) does not tell the devices apart, so no device gets it, and one that already took it from an
        earlier scan loses it."""
        shared = await session.scalar(
            select(DiscoveredCandidate.id)
            .where(
                DiscoveredCandidate.candidate_type == CandidateType.SERVICE,
                func.json_extract(DiscoveredCandidate.raw_attributes, "$.tls.common_name") == name,
                func.json_extract(DiscoveredCandidate.raw_attributes, "$.ip") != device.primary_ip,
            )
            .limit(1)
        )
        if shared is None:
            return False
        holders = await session.scalars(
            select(Device).where(Device.hostname == clean(name), Device.hostname_source == "tls")
        )
        for holder in holders:
            if holder.display_name == holder.hostname:
                holder.display_name = holder.primary_ip or holder.display_name
            holder.hostname = holder.hostname_source = None
        await session.commit()
        return True

    async def set_hostname(self, device_id: int, name: str | None, source: str) -> None:
        """Offers a host name for a device; it is applied only if `source` is at least as trustworthy as
        the name the device already has (see discovery/hostnames.py)."""
        async with self._databases.app_session_factory() as session:
            device = await session.get(Device, device_id)
            if device is None:
                return
            if source == "tls" and clean(name) and await self._certificate_is_shared(session, device, name):
                return
            if apply_hostname(device, name, source):
                await session.commit()

    async def list_candidates(
        self, status: CandidateStatus | None, candidate_type: CandidateType | None = None
    ) -> list[DiscoveredCandidate]:
        async with self._databases.app_session_factory() as session:
            query = select(DiscoveredCandidate).order_by(DiscoveredCandidate.last_seen_at.desc())
            query = query.where(DiscoveredCandidate.status == (status or CandidateStatus.PENDING))
            if candidate_type is not None:
                query = query.where(DiscoveredCandidate.candidate_type == candidate_type)
            result = await session.execute(query)
            return list(result.scalars().all())

    async def accept_device(
        self, candidate_id: int, device_type: DeviceType, display_name: str | None
    ) -> Device:
        """Device candidates are now auto-provisioned on first observation (see
        `_record_device`), so this only ever applies to a candidate that is
        still `pending` - in practice none created after that change. Kept for
        API stability; guards against double-provisioning a candidate that's
        already been turned into a Device."""
        async with self._databases.app_session_factory() as session:
            candidate = await session.get(DiscoveredCandidate, candidate_id)
            if (
                candidate is None
                or candidate.candidate_type != CandidateType.DEVICE
                or candidate.status != CandidateStatus.PENDING
            ):
                raise CandidateNotFoundError(f"Device candidate {candidate_id} not found")

            site = await ensure_default_site(session)
            attrs = candidate.raw_attributes
            device = Device(
                site_id=site.id,
                network_id=candidate.network_id,
                hostname=attrs.get("hostname"),
                display_name=display_name or attrs.get("hostname") or attrs.get("ip") or "Unnamed device",
                primary_ip=attrs.get("ip"),
                device_type=device_type,
            )
            session.add(device)
            await session.flush()

            if attrs.get("ip"):
                session.add(
                    DeviceAddress(
                        device_id=device.id,
                        ip_address=attrs["ip"],
                        mac_address=attrs.get("mac"),
                        is_primary=True,
                    )
                )

            candidate.status = CandidateStatus.ACCEPTED
            candidate.resulting_device_id = device.id
            await session.commit()
            await session.refresh(device)
            return device

    async def accept_service(
        self,
        candidate_id: int,
        service_type: ServiceType,
        name: str | None,
        device_id: int | None,
        config: dict[str, Any],
    ) -> Service:
        async with self._databases.app_session_factory() as session:
            candidate = await session.get(DiscoveredCandidate, candidate_id)
            if candidate is None or candidate.candidate_type != CandidateType.SERVICE:
                raise CandidateNotFoundError(f"Service candidate {candidate_id} not found")

            if candidate.status not in (CandidateStatus.PENDING, CandidateStatus.EXPIRED) or (
                candidate.resulting_service_id is not None
            ):
                raise CandidateStateError(f"Candidate {candidate_id} is already {candidate.status.value}")

            attrs = candidate.raw_attributes
            if device_id is None and attrs.get("ip"):
                # The discovery page never asks a user to pick a device for a
                # service candidate - auto-link it to whichever Device already
                # owns this IP (auto-provisioned at observation time, see
                # record_device_observation) so the Services table can show
                # its vendor/name instead of always rendering "-".
                result = await session.execute(
                    select(DeviceAddress.device_id).where(DeviceAddress.ip_address == attrs["ip"])
                )
                device_id = result.scalars().first()

            service = Service(
                device_id=device_id,
                name=name or f"{attrs.get('ip')}:{attrs.get('port')}",
                service_type=service_type,
                config=config,
            )
            session.add(service)
            await session.flush()

            candidate.status = CandidateStatus.ACCEPTED
            candidate.resulting_service_id = service.id
            await session.commit()
            await session.refresh(service)
            return service

    async def ignore(self, candidate_id: int) -> None:
        async with self._databases.app_session_factory() as session:
            candidate = await session.get(DiscoveredCandidate, candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(f"Candidate {candidate_id} not found")
            candidate.status = CandidateStatus.IGNORED
            await session.commit()

    async def expire_stale(self, older_than: datetime.timedelta) -> int:
        cutoff = utcnow() - older_than
        async with self._databases.app_session_factory() as session:
            result = await session.execute(
                select(DiscoveredCandidate).where(
                    DiscoveredCandidate.status == CandidateStatus.PENDING,
                    DiscoveredCandidate.last_seen_at < cutoff,
                )
            )
            stale = list(result.scalars().all())
            for candidate in stale:
                candidate.status = CandidateStatus.EXPIRED
            await session.commit()
            return len(stale)


def _default_config(service_type: str, ip: str, port: int) -> dict[str, Any]:
    if service_type in ("http", "https"):
        return {"url": f"{service_type}://{ip}:{port}"}
    return {"host": ip, "port": port}


class DiscoveredServiceStore:
    """Writes scan/AI findings straight into the Services table as unmanaged
    rows (the supervisor only polls managed=True), the same way discovered
    devices are auto-populated - see docs/decisions.md."""

    def __init__(self, databases: Databases) -> None:
        self._databases = databases

    async def upsert(
        self,
        *,
        device_id: int | None,
        ip: str,
        port: int,
        service_type: str,
        source: str,
        fingerprint: dict[str, Any] | None = None,
    ) -> int:
        """Creates the (device, port) service if new; otherwise refreshes
        last_checked_at-independent fields without touching a managed row's
        type/config (a human or accept flow owns those). Returns the id."""
        # select-then-insert: serialize, or a scan, its nmap follow-up and an AI run can each insert the same
        # (device, port).
        async with named_lock("service-upsert"), self._databases.app_session_factory() as session:
            query = select(Service).where(Service.port == port)
            query = query.where(
                Service.device_id == device_id if device_id is not None else Service.device_id.is_(None)
            )
            if device_id is None:
                query = query.where(Service.name.like(f"%{ip}:{port}"))
            existing = (await session.execute(query)).scalars().first()
            if existing is None and device_id is not None:
                # Adopt a service created before its host had a Device (matched by
                # the ip:port its name carries) instead of creating a duplicate.
                orphan_query = select(Service).where(
                    Service.device_id.is_(None), Service.port == port, Service.name.like(f"%{ip}:{port}")
                ).order_by(Service.managed.desc(), Service.id)
                existing = (await session.execute(orphan_query)).scalars().first()
                if existing is not None:
                    existing.device_id = device_id
            stamped = (
                {**fingerprint, "fingerprinted_at": utcnow().isoformat()} if fingerprint else None
            )

            if existing is not None:
                if stamped:
                    existing.fingerprint = stamped
                await session.commit()
                return existing.id

            label = (fingerprint or {}).get("name") or "tcp"
            service = Service(
                device_id=device_id,
                name=f"{label} {ip}:{port}",
                service_type=ServiceType(service_type),
                config=_default_config(service_type, ip, port),
                managed=False,
                port=port,
                source=source,
                fingerprint=stamped,
            )
            session.add(service)
            await session.commit()
            return service.id

    async def set_fingerprint(self, service_id: int, fingerprint: dict[str, Any]) -> None:
        async with self._databases.app_session_factory() as session:
            service = await session.get(Service, service_id)
            if service is None:
                return
            service.fingerprint = {**fingerprint, "fingerprinted_at": utcnow().isoformat()}
            await session.commit()

    async def reconcile(self) -> int:
        """Startup repair for services created before `port`/device linking
        existed, or orphaned by legacy device candidates:
        1. derive `port` from config so scans can match them;
        2. link services with no device to the Device owning their host IP;
        3. merge scan-created unmanaged duplicates into the managed service for
           the same host:port (keeping its fingerprint), so nothing shows twice.
        Returns the number of rows changed."""
        changed = 0
        async with self._databases.app_session_factory() as session:
            services = list((await session.execute(select(Service).order_by(Service.id))).scalars().all())
            owners = {
                ip: device_id
                for ip, device_id in (
                    await session.execute(select(DeviceAddress.ip_address, DeviceAddress.device_id))
                ).all()
            }

            removed_ids: set[int] = set()
            by_key: dict[tuple[str, int], list[Service]] = {}
            for service in services:
                host, port = _host_and_port(service.config or {})
                if service.port is None and port is not None:
                    service.port = port
                    changed += 1
                if service.device_id is None and host in owners:
                    service.device_id = owners[host]
                    changed += 1
                if host is not None and service.port is not None:
                    by_key.setdefault((host, service.port), []).append(service)
                elif service.port is not None:
                    ip_in_name = service.name.rsplit(":", 1)[0].split()[-1]
                    by_key.setdefault((ip_in_name, service.port), []).append(service)

            for group in by_key.values():
                managed = [x for x in group if x.managed]
                scanned = [x for x in group if not x.managed and x.source in ("scan", "ai")]
                if not managed or not scanned:
                    continue
                keeper = managed[0]
                for dup in scanned:
                    if dup.fingerprint and not keeper.fingerprint:
                        keeper.fingerprint = dup.fingerprint
                    await session.delete(dup)
                    removed_ids.add(dup.id)
                    changed += 1

            # Scan and AI found the same (device, port) more than once (two upserts raced before they were
            # serialized): keep the oldest and fold the others into it.
            first_seen: dict[tuple[int, int], Service] = {}
            for service in services:
                if (
                    service.id in removed_ids
                    or service.managed
                    or service.device_id is None
                    or service.port is None
                    or service.source not in ("scan", "ai")
                ):
                    continue
                key = (service.device_id, service.port)
                keeper = first_seen.setdefault(key, service)
                if keeper is not service:
                    if service.fingerprint and not keeper.fingerprint:
                        keeper.fingerprint = service.fingerprint
                    await session.delete(service)
                    changed += 1
            await session.commit()
        return changed


def _host_and_port(config: dict[str, Any]) -> tuple[str | None, int | None]:
    """The host/port a service's config points at (None where it has none)."""
    if config.get("url"):
        parsed = urlparse(str(config["url"]))
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            port = None
        return parsed.hostname, port
    port = config.get("port")
    host = config.get("host")
    if isinstance(port, str) and port.isdigit():
        port = int(port)
    return (str(host) if host else None), (port if isinstance(port, int) else None)
