import asyncio

import pytest

from app.alerting.engine import AlertEngine
from app.alerting.notifier import LogNotifier
from app.credentials.models import CredentialsBase
from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_site
from app.domain.enums import AlertConditionType, AlertState, DeviceType, EntityType
from app.domain.metrics_models import CheckResult, MetricSample, MetricsBase
from app.domain.models import AlertEvent, AlertRule, AlertStateRow, Device, Event
from app.domain.models import Base as AppBase


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


@pytest.fixture
async def device_id(databases) -> int:
    async with databases.app_session_factory() as session:
        site = await ensure_default_site(session)
        device = Device(site_id=site.id, display_name="dev1", device_type=DeviceType.LINUX)
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return device.id


async def _create_device_down_rule(databases, **param_overrides) -> AlertRule:
    # staleness_seconds must stay well above the test's own sleeps, or a
    # single successful check "goes stale again" by the time we assert
    # recovery - it's an SLA on check freshness, not a state-machine timer.
    params = {"staleness_seconds": 5.0, "for_duration_seconds": 0.05, "recovery_duration_seconds": 0.05}
    params.update(param_overrides)
    async with databases.app_session_factory() as session:
        rule = AlertRule(
            name="device-down",
            condition_type=AlertConditionType.DEVICE_DOWN,
            entity_selector={"scope": "all"},
            parameters=params,
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule


async def _get_state(databases, rule_id: int, device_id: int) -> AlertStateRow | None:
    from sqlalchemy import select

    async with databases.app_session_factory() as session:
        result = await session.execute(
            select(AlertStateRow).where(
                AlertStateRow.alert_rule_id == rule_id,
                AlertStateRow.entity_type == EntityType.DEVICE,
                AlertStateRow.entity_id == device_id,
            )
        )
        return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_device_down_full_cycle_produces_expected_transitions(databases, device_id) -> None:
    rule = await _create_device_down_rule(databases)
    engine = AlertEngine(databases, LogNotifier(databases))

    # No successful checks yet -> immediate breach -> ok -> pending
    await engine.evaluate_entity(EntityType.DEVICE, device_id)
    state = await _get_state(databases, rule.id, device_id)
    assert state.state == AlertState.PENDING

    # Still breaching once for_duration has elapsed -> pending -> firing (notify)
    await asyncio.sleep(0.1)
    await engine.evaluate_entity(EntityType.DEVICE, device_id)
    state = await _get_state(databases, rule.id, device_id)
    assert state.state == AlertState.FIRING

    # A successful check clears the breach -> firing -> resolved (notify)
    async with databases.metrics_session_factory() as session:
        session.add(CheckResult(entity_type=EntityType.DEVICE, entity_id=device_id, success=True))
        await session.commit()
    await engine.evaluate_entity(EntityType.DEVICE, device_id)
    state = await _get_state(databases, rule.id, device_id)
    assert state.state == AlertState.RESOLVED

    # Recovery window elapses with no new breach -> resolved -> ok
    await asyncio.sleep(0.1)
    await engine.evaluate_entity(EntityType.DEVICE, device_id)
    state = await _get_state(databases, rule.id, device_id)
    assert state.state == AlertState.OK

    async with databases.app_session_factory() as session:
        from sqlalchemy import select

        transitions = (
            await session.execute(
                select(AlertEvent.from_state, AlertEvent.to_state)
                .where(AlertEvent.alert_state_id == state.id)
                .order_by(AlertEvent.ts)
            )
        ).all()
    assert transitions == [
        (AlertState.OK, AlertState.PENDING),
        (AlertState.PENDING, AlertState.FIRING),
        (AlertState.FIRING, AlertState.RESOLVED),
        (AlertState.RESOLVED, AlertState.OK),
    ]

    async with databases.app_session_factory() as session:
        from sqlalchemy import select as sa_select

        events = (await session.execute(sa_select(Event).where(Event.category == "alert"))).scalars().all()
    # Only firing and resolved should have notified (pending/ok transitions are silent)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_disabled_rule_is_never_evaluated(databases, device_id) -> None:
    async with databases.app_session_factory() as session:
        rule = AlertRule(
            name="disabled-rule",
            condition_type=AlertConditionType.DEVICE_DOWN,
            entity_selector={"scope": "all"},
            enabled=False,
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)

    engine = AlertEngine(databases, LogNotifier(databases))
    await engine.evaluate_entity(EntityType.DEVICE, device_id)

    assert await _get_state(databases, rule.id, device_id) is None


@pytest.mark.asyncio
async def test_entity_selector_scoping_excludes_unlisted_devices(databases, device_id) -> None:
    async with databases.app_session_factory() as session:
        rule = AlertRule(
            name="scoped-rule",
            condition_type=AlertConditionType.DEVICE_DOWN,
            entity_selector={"scope": "device", "device_ids": [device_id + 999]},
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)

    engine = AlertEngine(databases, LogNotifier(databases))
    await engine.evaluate_entity(EntityType.DEVICE, device_id)

    assert await _get_state(databases, rule.id, device_id) is None


@pytest.mark.asyncio
async def test_repeated_flapping_suppresses_notification(databases, device_id) -> None:
    # HIGH_CPU gives precise, instant breach control via metric value, unlike
    # DEVICE_DOWN's staleness-based check which can't be toggled without
    # waiting real time relative to staleness_seconds.
    async with databases.app_session_factory() as session:
        rule = AlertRule(
            name="high-cpu",
            condition_type=AlertConditionType.HIGH_CPU,
            entity_selector={"scope": "all"},
            parameters={"threshold": 90.0, "for_duration_seconds": 0.0, "recovery_duration_seconds": 0.0},
            flap_dampening={"window_seconds": 600.0, "threshold": 1},
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)

    engine = AlertEngine(databases, LogNotifier(databases))

    async def set_cpu(value: float) -> None:
        async with databases.metrics_session_factory() as session:
            session.add(
                MetricSample(
                    entity_type=EntityType.DEVICE,
                    entity_id=device_id,
                    metric_name="cpu_percent",
                    value=value,
                )
            )
            await session.commit()

    # ok -> pending -> firing
    await set_cpu(99.0)
    await engine.evaluate_entity(EntityType.DEVICE, device_id)
    await engine.evaluate_entity(EntityType.DEVICE, device_id)
    assert (await _get_state(databases, rule.id, device_id)).state == AlertState.FIRING

    # firing -> resolved
    await set_cpu(10.0)
    await engine.evaluate_entity(EntityType.DEVICE, device_id)
    assert (await _get_state(databases, rule.id, device_id)).state == AlertState.RESOLVED

    # resolved -> firing again immediately: with threshold=1, this flaps
    await set_cpu(99.0)
    await engine.evaluate_entity(EntityType.DEVICE, device_id)

    state = await _get_state(databases, rule.id, device_id)
    assert state.state == AlertState.FLAPPING
