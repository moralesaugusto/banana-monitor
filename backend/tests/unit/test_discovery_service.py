import datetime

import pytest
from sqlalchemy import select

from app.credentials.models import CredentialsBase
from app.db.session import get_databases
from app.discovery.service import CandidateNotFoundError, DiscoveryService
from app.domain.enums import CandidateStatus, DeviceType, ServiceType
from app.domain.metrics_models import MetricsBase
from app.domain.models import Base as AppBase
from app.domain.models import Device, DiscoveredCandidate


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with dbs.metrics_engine.begin() as conn:
        await conn.run_sync(MetricsBase.metadata.create_all)
    async with dbs.credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


@pytest.mark.asyncio
async def test_record_device_observation_auto_provisions_device(databases) -> None:
    """A never-seen-before host is immediately turned into a real (unmanaged)
    Device - see docs/decisions.md "Auto-populate discovered devices" -
    instead of waiting as a pending candidate."""
    service = DiscoveryService(databases)

    device_id = await service.record_device_observation(
        network_id=None, ip="192.168.1.10", mac="aa:bb:cc:dd:ee:ff", hostname=None,
        open_ports=[22], via="network_scan",
    )
    device_id_again = await service.record_device_observation(
        network_id=None, ip="192.168.1.10", mac="aa:bb:cc:dd:ee:ff", hostname="host1",
        open_ports=[22, 80], via="network_scan",
    )

    assert device_id_again == device_id

    candidates = await service.list_candidates(CandidateStatus.ACCEPTED)
    assert len(candidates) == 1
    assert candidates[0].times_seen == 2
    assert candidates[0].raw_attributes["hostname"] == "host1"
    assert candidates[0].resulting_device_id == device_id
    assert await service.list_candidates(CandidateStatus.PENDING) == []

    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        # first observation had no hostname, so display_name fell back to the
        # IP at creation time; a later observation's hostname only refreshes
        # raw_attributes/last_seen_at, never display_name - a human (or
        # PATCH /api/devices/{id}) owns that field once it's set.
        assert device.display_name == "192.168.1.10"
        assert device.primary_ip == "192.168.1.10"
        assert device.managed is False
        assert device.device_type == DeviceType.OTHER


@pytest.mark.asyncio
async def test_accept_device_on_already_provisioned_candidate_raises(databases) -> None:
    """Guards against double-provisioning: a device candidate is auto-accepted
    on first observation now, so accept_device must refuse to run again."""
    service = DiscoveryService(databases)
    await service.record_device_observation(
        network_id=None, ip="192.168.1.10", mac=None, hostname=None, open_ports=[], via="network_scan"
    )
    candidate = (await service.list_candidates(CandidateStatus.ACCEPTED))[0]

    with pytest.raises(CandidateNotFoundError):
        await service.accept_device(candidate.id, DeviceType.LINUX, None)


@pytest.mark.asyncio
async def test_accept_service_creates_service(databases) -> None:
    service = DiscoveryService(databases)
    await service.record_service_observation(
        network_id=None, ip="192.168.1.10", port=443, protocol="https", attributes={}, via="network_scan"
    )
    candidate = (await service.list_candidates(CandidateStatus.PENDING))[0]

    created = await service.accept_service(candidate.id, ServiceType.HTTPS, "web", None, {"url": "https://192.168.1.10"})

    assert created.name == "web"
    assert created.service_type == ServiceType.HTTPS


@pytest.mark.asyncio
async def test_accept_service_auto_links_device_by_ip(databases) -> None:
    """The Discovery page never asks a user to pick a device for a service
    candidate - accept_service must auto-link it to whichever Device was
    already auto-provisioned at that IP, so the Services table can show its
    name/vendor instead of always rendering "-"."""
    service = DiscoveryService(databases)
    device_id = await service.record_device_observation(
        network_id=None, ip="192.168.1.50", mac="aa:bb:cc:00:00:01", hostname="nas",
        open_ports=[443], via="network_scan",
    )
    await service.record_service_observation(
        network_id=None, ip="192.168.1.50", port=443, protocol="https", attributes={}, via="network_scan"
    )
    candidates = await service.list_candidates(CandidateStatus.PENDING)
    service_candidate = next(c for c in candidates if c.candidate_type.value == "service")

    created = await service.accept_service(
        service_candidate.id, ServiceType.HTTPS, None, None, {"url": "https://192.168.1.50"}
    )

    assert created.device_id == device_id


@pytest.mark.asyncio
async def test_record_device_observation_infers_windows_from_os_hint(databases) -> None:
    service = DiscoveryService(databases)
    device_id = await service.record_device_observation(
        network_id=None, ip="192.168.1.60", mac=None, hostname=None, open_ports=[445],
        via="network_scan", os_name="Microsoft Windows 10", os_accuracy=95,
    )

    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        assert device.device_type == DeviceType.WINDOWS


@pytest.mark.asyncio
async def test_accept_device_wrong_candidate_type_raises(databases) -> None:
    service = DiscoveryService(databases)
    await service.record_service_observation(
        network_id=None, ip="192.168.1.10", port=443, protocol="https", attributes={}, via="network_scan"
    )
    candidate = (await service.list_candidates(CandidateStatus.PENDING))[0]

    with pytest.raises(CandidateNotFoundError):
        await service.accept_device(candidate.id, DeviceType.LINUX, None)


@pytest.mark.asyncio
async def test_expire_stale_marks_old_pending_candidates(databases) -> None:
    """Device candidates auto-accept now (see above), so staleness/expiry only
    ever applies to service candidates - exercise that path here."""
    service = DiscoveryService(databases)
    await service.record_service_observation(
        network_id=None, ip="192.168.1.10", port=443, protocol="https", attributes={}, via="network_scan"
    )
    candidate = (await service.list_candidates(CandidateStatus.PENDING))[0]

    async with databases.app_session_factory() as session:
        db_candidate = await session.get(DiscoveredCandidate, candidate.id)
        db_candidate.last_seen_at = db_candidate.last_seen_at - datetime.timedelta(days=31)
        await session.commit()

    expired_count = await service.expire_stale(datetime.timedelta(days=30))

    assert expired_count == 1
    assert await service.list_candidates(CandidateStatus.PENDING) == []
    assert len(await service.list_candidates(CandidateStatus.EXPIRED)) == 1


@pytest.mark.asyncio
async def test_legacy_pending_device_candidate_is_provisioned_and_orphan_service_adopted(databases) -> None:
    from sqlalchemy import select

    from app.discovery.service import DiscoveredServiceStore
    from app.domain.enums import CandidateStatus, CandidateType, ServiceType
    from app.domain.models import DiscoveredCandidate, Service

    async with databases.app_session_factory() as session:
        session.add(
            DiscoveredCandidate(
                candidate_type=CandidateType.DEVICE, fingerprint="10.9.9.9", discovered_via="network_scan",
                raw_attributes={"ip": "10.9.9.9"}, status=CandidateStatus.PENDING,
            )
        )
        session.add(
            Service(name="10.9.9.9:443", service_type=ServiceType.HTTPS, config={"url": "https://10.9.9.9"},
                    managed=True, port=443)
        )
        await session.commit()

    service = DiscoveryService(databases)
    device_id = await service.record_device_observation(
        network_id=None, ip="10.9.9.9", mac=None, hostname=None, open_ports=[443], via="network_scan"
    )
    assert device_id is not None

    await DiscoveredServiceStore(databases).upsert(
        device_id=device_id, ip="10.9.9.9", port=443, service_type="https", source="scan"
    )
    async with databases.app_session_factory() as session:
        services = (await session.execute(select(Service))).scalars().all()
    assert len(services) == 1 and services[0].device_id == device_id and services[0].managed is True


@pytest.mark.asyncio
async def test_auto_accept_services_creates_a_monitored_service(databases) -> None:
    from app.domain.bootstrap import ensure_default_discovery_settings
    from app.domain.models import Service

    service = DiscoveryService(databases)
    await service.record_service_observation(
        network_id=None, ip="10.0.0.5", port=80, protocol="http", attributes={}, via="network_scan"
    )
    assert len(await service.list_candidates(CandidateStatus.PENDING)) == 1  # off by default

    async with databases.app_session_factory() as session:
        (await ensure_default_discovery_settings(session)).auto_accept_services = True
        await session.commit()
    await service.record_service_observation(
        network_id=None, ip="10.0.0.6", port=443, protocol="https", attributes={}, via="network_scan"
    )
    await service.record_service_observation(
        network_id=None, ip="10.0.0.7", port=5432, protocol="tcp", attributes={}, via="network_scan"
    )
    await service.record_service_observation(  # re-seen while still pending: accepted now
        network_id=None, ip="10.0.0.5", port=80, protocol="http", attributes={}, via="network_scan"
    )

    assert await service.list_candidates(CandidateStatus.PENDING) == []
    async with databases.app_session_factory() as session:
        configs = {s.config.get("url") or s.config["port"] for s in await session.scalars(select(Service))}
    assert configs == {"http://10.0.0.5:80", "https://10.0.0.6:443", 5432}
