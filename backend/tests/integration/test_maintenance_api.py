import datetime

import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.domain.enums import AlertConditionType, AlertState, EntityType
from app.domain.metrics_models import CheckResult
from app.domain.models import (
    AiMessage,
    AiRun,
    AlertEvent,
    AlertRule,
    AlertStateRow,
    Event,
    Report,
)


async def _seed() -> None:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        run = AiRun(status="done")
        rule = AlertRule(name="r", condition_type=AlertConditionType.DEVICE_DOWN)
        session.add_all([run, rule, Report(title="t"), Event(source="s", category="c", message="m")])
        await session.flush()
        state = AlertStateRow(alert_rule_id=rule.id, entity_type=EntityType.DEVICE, entity_id=1)
        session.add_all([AiMessage(run_id=run.id, topic="x", sender="a", correlation_id="c"), state])
        await session.flush()
        session.add(
            AlertEvent(alert_state_id=state.id, from_state=AlertState.OK, to_state=AlertState.FIRING)
        )
        await session.commit()
    async with databases.metrics_session_factory() as session:
        session.add(CheckResult(entity_type=EntityType.DEVICE, entity_id=1, success=True))
        await session.commit()


@pytest.mark.asyncio
async def test_counts_and_clean_each_target(client: AsyncClient) -> None:
    await _seed()
    counts = (await client.get("/api/maintenance/counts")).json()
    assert counts["reports"] == 1 and counts["events"] == 1 and counts["alerts"] == 2
    assert counts["bus"] == 1 and counts["history"] == 1 and counts["ai_runs"] == 1

    for target, key, expected in [
        ("reports", "reports", 1),
        ("events", "events", 1),
        ("alerts", "alerts", 2),
        ("bus", "bus", 1),
        ("history", "history", 1),
        ("ai-runs", "ai_runs", 1),
    ]:
        response = await client.delete(f"/api/maintenance/{target}")
        assert response.status_code == 200
        assert response.json() == {"deleted": expected}
        assert (await client.get("/api/maintenance/counts")).json()[key] == 0

    rules = await client.get("/api/alerts/rules")
    assert len(rules.json()) == 1  # the rule survives


@pytest.mark.asyncio
async def test_bus_and_runs_cannot_be_cleaned_during_a_run(client: AsyncClient) -> None:
    async with get_databases().app_session_factory() as session:
        session.add(AiRun(status="running"))
        await session.commit()
    assert (await client.delete("/api/maintenance/bus")).status_code == 409
    assert (await client.delete("/api/maintenance/ai-runs")).status_code == 409
    assert (await client.delete("/api/maintenance/events")).status_code == 200


@pytest.mark.asyncio
async def test_unknown_target_is_rejected(client: AsyncClient) -> None:
    assert (await client.delete("/api/maintenance/devices")).status_code == 422


@pytest.mark.asyncio
async def test_audit_records_changes_but_not_reads_or_failures(client: AsyncClient) -> None:
    await client.get("/api/events")
    await client.delete("/api/maintenance/events")
    await client.delete("/api/maintenance/nope")
    entries = (await client.get("/api/audit")).json()
    assert [(e["method"], e["path"], e["status"]) for e in entries] == [
        ("DELETE", "/api/maintenance/events", 200)
    ]
    assert entries[0]["actor"]

    assert (await client.delete("/api/audit")).json() == {"deleted": 1}
    after = (await client.get("/api/audit")).json()
    assert [e["path"] for e in after] == ["/api/audit"]  # the cleaning itself is recorded
    assert datetime.datetime.fromisoformat(after[0]["ts"])
