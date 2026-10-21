import pytest
from httpx import AsyncClient

from app.alerting.engine import AlertEngine
from app.alerting.notifier import LogNotifier
from app.db.session import get_databases
from app.domain.enums import EntityType


@pytest.mark.asyncio
async def test_create_list_update_delete_rule(client: AsyncClient) -> None:
    response = await client.post(
        "/api/alerts/rules",
        json={
            "name": "device-down",
            "condition_type": "device_down",
            "parameters": {"staleness_seconds": 90},
        },
    )
    assert response.status_code == 201
    rule = response.json()
    assert rule["enabled"] is True
    assert rule["severity"] == "warning"

    response = await client.get("/api/alerts/rules")
    assert len(response.json()) == 1

    response = await client.patch(f"/api/alerts/rules/{rule['id']}", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    response = await client.delete(f"/api/alerts/rules/{rule['id']}")
    assert response.status_code == 204

    assert (await client.get("/api/alerts/rules")).json() == []


@pytest.mark.asyncio
async def test_update_missing_rule_404(client: AsyncClient) -> None:
    response = await client.patch("/api/alerts/rules/999", json={"enabled": False})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_states_endpoint_defaults_to_active_only(client: AsyncClient) -> None:
    response = await client.get("/api/alerts/states")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_firing_alert_surfaces_via_states_events_endpoints(client: AsyncClient) -> None:
    device = (
        await client.post("/api/devices", json={"display_name": "dev1", "device_type": "linux"})
    ).json()
    await client.post(
        "/api/alerts/rules",
        json={
            "name": "device-down",
            "condition_type": "device_down",
            "parameters": {"staleness_seconds": 5.0, "for_duration_seconds": 0.0},
        },
    )

    engine = AlertEngine(get_databases(), LogNotifier(get_databases()))
    await engine.evaluate_entity(EntityType.DEVICE, device["id"])
    await engine.evaluate_entity(EntityType.DEVICE, device["id"])

    response = await client.get("/api/alerts/states")
    assert response.status_code == 200
    states = response.json()
    assert len(states) == 1
    assert states[0]["state"] == "firing"
    assert states[0]["entity_id"] == device["id"]

    response = await client.get(f"/api/alerts/states/{states[0]['id']}/events")
    assert response.status_code == 200
    transitions = [(e["from_state"], e["to_state"]) for e in response.json()]
    assert ("pending", "firing") in transitions

    response = await client.get("/api/events")
    assert response.status_code == 200
    assert any(e["category"] == "alert" for e in response.json())
