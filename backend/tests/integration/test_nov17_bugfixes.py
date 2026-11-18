import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.alerting.engine import AlertEngine
from app.alerting.notifier import LogNotifier
from app.db.session import get_databases
from app.discovery import reachability
from app.domain.enums import EntityType, HealthStatus
from app.domain.metrics_models import CheckResult, MetricSample
from app.domain.models import AlertEvent, AlertStateRow
from app.metrics.queries import get_latest_metric_values, get_latest_metric_values_for_entity
from app.metrics.writer import get_metrics_writer


@pytest.mark.asyncio
async def test_latest_metric_queries_ignore_same_timestamp_rows_of_other_entities(
    client: AsyncClient,
) -> None:
    ts = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    def row(entity_type: EntityType, entity_id: int, metric: str, value: float) -> MetricSample:
        return MetricSample(
            entity_type=entity_type, entity_id=entity_id, metric_name=metric, ts=ts, value=value
        )

    async with get_databases().metrics_session_factory() as session:
        session.add_all(
            [
                row(EntityType.DEVICE, 1, "cpu", 10.0),
                row(EntityType.SERVICE, 1, "cpu", 99.0),
                row(EntityType.DEVICE, 1, "mem", 55.0),
                row(EntityType.DEVICE, 2, "cpu", 77.0),
            ]
        )
        await session.commit()
        assert await get_latest_metric_values(session, EntityType.DEVICE, "cpu", [1]) == {1: 10.0}
        assert await get_latest_metric_values_for_entity(session, EntityType.DEVICE, 1) == {
            "cpu": 10.0,
            "mem": 55.0,
        }


@pytest.mark.asyncio
async def test_reachability_records_check_results_and_alerts_on_down_then_recovers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = (
        await client.post(
            "/api/devices", json={"display_name": "plain", "device_type": "other", "primary_ip": "10.0.1.1"}
        )
    ).json()
    await client.post(
        "/api/alerts/rules",
        json={
            "name": "down",
            "condition_type": "device_down",
            "parameters": {"staleness_seconds": 5.0, "for_duration_seconds": 0.0},
        },
    )
    databases = get_databases()
    status = HealthStatus.UP

    async def fake_probe(ip: str, ports: list[int]) -> HealthStatus:
        return status

    monkeypatch.setattr(reachability, "probe_device", fake_probe)
    writer = get_metrics_writer()

    async def states() -> list[str]:
        response = await client.get("/api/alerts/states?active_only=false")
        return [s["state"] for s in response.json()]

    await reachability.run_reachability(databases)
    await writer._flush()
    async with databases.metrics_session_factory() as session:
        results = list(await session.scalars(select(CheckResult.success)))
    assert results == [True]
    await AlertEngine(databases, LogNotifier(databases)).evaluate_entity(EntityType.DEVICE, device["id"])
    assert "firing" not in await states()

    status = HealthStatus.DOWN
    await reachability.run_reachability(databases)
    await writer._flush()
    async with databases.metrics_session_factory() as session:
        results = list(await session.scalars(select(CheckResult.success).order_by(CheckResult.id)))
    assert results == [True, False]


@pytest.mark.asyncio
async def test_delete_rule_with_state_and_events(client: AsyncClient) -> None:
    device = (await client.post("/api/devices", json={"display_name": "d", "device_type": "linux"})).json()
    rule = (
        await client.post(
            "/api/alerts/rules",
            json={
                "name": "down",
                "condition_type": "device_down",
                "parameters": {"staleness_seconds": 5.0, "for_duration_seconds": 0.0},
            },
        )
    ).json()
    databases = get_databases()
    engine = AlertEngine(databases, LogNotifier(databases))
    await engine.evaluate_entity(EntityType.DEVICE, device["id"])
    await engine.evaluate_entity(EntityType.DEVICE, device["id"])
    async with databases.app_session_factory() as session:
        assert (await session.scalars(select(AlertEvent))).first() is not None

    response = await client.delete(f"/api/alerts/rules/{rule['id']}")
    assert response.status_code == 204
    async with databases.app_session_factory() as session:
        assert (await session.scalars(select(AlertStateRow))).first() is None
        assert (await session.scalars(select(AlertEvent))).first() is None


@pytest.mark.asyncio
async def test_embedding_and_fallback_credentials_block_delete(client: AsyncClient) -> None:
    created = await client.post(
        "/api/credentials", json={"label": "k", "credential_type": "api_token", "secret": {"token": "x"}}
    )
    assert created.status_code == 201, created.text
    cred_id = created.json()["id"]

    from app.domain.bootstrap import ensure_default_ai_mode_settings

    async with get_databases().app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        settings.knowledge_embedding_credential_id = cred_id
        await session.commit()
    response = await client.delete(f"/api/credentials/{cred_id}")
    assert response.status_code == 409
    assert "knowledge base embeddings" in response.json()["detail"]

    await client.get("/api/ai-mode/agents")  # seeds the default agents
    async with get_databases().app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        settings.knowledge_embedding_credential_id = None
        from app.domain.models import AiAgent

        agent = (await session.scalars(select(AiAgent))).first()
        assert agent is not None
        agent.fallback_credential_id = cred_id
        await session.commit()
    response = await client.delete(f"/api/credentials/{cred_id}")
    assert response.status_code == 409
    assert "fallback key" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["interval_seconds", "timeout_seconds"])
@pytest.mark.parametrize("value", [0, -5])
async def test_service_rejects_non_positive_intervals(client: AsyncClient, field: str, value: int) -> None:
    body = {"name": "web", "service_type": "https", "config": {"url": "https://example.com"}}
    assert (await client.post("/api/services", json=body)).status_code == 201
    body["config"][field] = value
    response = await client.post("/api/services", json=body)
    assert response.status_code == 400, response.text
