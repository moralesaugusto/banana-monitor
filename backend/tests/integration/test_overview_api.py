import pytest
from httpx import AsyncClient

from app.alerting.engine import AlertEngine
from app.alerting.notifier import LogNotifier
from app.db.session import get_databases
from app.domain.enums import EntityType, HealthStatus
from app.domain.models import Device


@pytest.mark.asyncio
async def test_overview_reflects_actual_status_counts(client: AsyncClient) -> None:
    up_device = (
        await client.post("/api/devices", json={"display_name": "up1", "device_type": "linux"})
    ).json()
    await client.post("/api/devices", json={"display_name": "down1", "device_type": "linux"})

    databases = get_databases()
    async with databases.app_session_factory() as session:
        device = await session.get(Device, up_device["id"])
        device.status = HealthStatus.UP
        await session.commit()

    await client.post(
        "/api/alerts/rules",
        json={
            "name": "device-down",
            "condition_type": "device_down",
            "parameters": {"staleness_seconds": 0, "for_duration_seconds": 0},
        },
    )
    engine = AlertEngine(databases, LogNotifier(databases))
    await engine.evaluate_entity(EntityType.DEVICE, up_device["id"])
    await engine.evaluate_entity(EntityType.DEVICE, up_device["id"])

    response = await client.get("/api/overview")
    assert response.status_code == 200
    summary = response.json()

    assert summary["devices"]["up"] == 1
    assert summary["devices"]["unknown"] == 1
    assert len(summary["firing_alerts"]) == 1
    assert any(e["category"] == "alert" for e in summary["recent_events"])


@pytest.mark.asyncio
async def test_health_trend_has_24_hourly_buckets_with_the_share_of_successful_checks(
    client: AsyncClient,
) -> None:
    import datetime

    from app.db.session import get_databases
    from app.domain.enums import EntityType
    from app.domain.metrics_models import CheckResult
    from app.domain.models import utcnow

    now = utcnow()
    async with get_databases().metrics_session_factory() as session:
        for success in (True, True, True, False):  # 3 of 4 device checks succeeded this hour
            session.add(CheckResult(entity_type=EntityType.DEVICE, entity_id=1, ts=now, success=success))
        old = now - datetime.timedelta(hours=30)  # outside the window
        session.add(CheckResult(entity_type=EntityType.SERVICE, entity_id=1, ts=old, success=False))
        await session.commit()

    buckets = (await client.get("/api/overview/health-trend")).json()["buckets"]
    assert len(buckets) == 24
    assert buckets[-1]["devices"] == 0.75 and buckets[-1]["services"] is None
    assert all(b["devices"] is None for b in buckets[:-1])
    assert all(b["services"] is None for b in buckets)
