import datetime

import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.discovery.service import DiscoveryService
from app.domain.enums import EntityType
from app.domain.metrics_models import MetricSample

SAMPLE_OUI_CSV = (
    "Registry,Assignment,Organization Name,Organization Address\n"
    'MA-L,9C4E36,"Raspberry Pi Trading Ltd",Cambridge UK\n'
)


@pytest.mark.asyncio
async def test_create_list_update_delete_service(client: AsyncClient) -> None:
    response = await client.post(
        "/api/services",
        json={"name": "web", "service_type": "https", "config": {"url": "https://example.com"}},
    )
    assert response.status_code == 201
    service = response.json()
    assert service["status"] == "unknown"
    assert service["config"] == {"url": "https://example.com"}

    response = await client.get("/api/services")
    assert response.status_code == 200
    assert len(response.json()) == 1

    response = await client.patch(f"/api/services/{service['id']}", json={"name": "https-web"})
    assert response.status_code == 200
    assert response.json()["name"] == "https-web"

    response = await client.delete(f"/api/services/{service['id']}")
    assert response.status_code == 204

    response = await client.get(f"/api/services/{service['id']}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_service_rejects_invalid_check_config(client: AsyncClient) -> None:
    response = await client.post(
        "/api/services", json={"name": "web", "service_type": "https", "config": {}}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_service_list_surfaces_latest_latency(client: AsyncClient) -> None:
    service = (
        await client.post(
            "/api/services",
            json={"name": "web", "service_type": "https", "config": {"url": "https://example.com"}},
        )
    ).json()

    now = datetime.datetime.now(datetime.UTC)
    databases = get_databases()
    async with databases.metrics_session_factory() as session:
        session.add(
            MetricSample(
                entity_type=EntityType.SERVICE,
                entity_id=service["id"],
                metric_name="latency_ms",
                value=12.5,
                ts=now - datetime.timedelta(seconds=10),
            )
        )
        session.add(
            MetricSample(
                entity_type=EntityType.SERVICE,
                entity_id=service["id"],
                metric_name="latency_ms",
                value=99.9,
                ts=now,
            )
        )
        await session.commit()

    response = await client.get("/api/services")
    assert response.json()[0]["last_latency_ms"] == 99.9

    response = await client.get(f"/api/services/{service['id']}")
    assert response.json()["last_latency_ms"] == 99.9


@pytest.mark.asyncio
async def test_service_list_surfaces_parent_device_vendor(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_download(timeout: float = 30.0) -> str:
        return SAMPLE_OUI_CSV

    monkeypatch.setattr("app.discovery.oui.download_oui_csv", fake_download)
    await client.post("/api/discovery/oui/update")

    discovery_service = DiscoveryService(get_databases())
    device_id = await discovery_service.record_device_observation(
        network_id=None, ip="192.168.1.50", mac="9c:4e:36:aa:bb:cc", hostname="pi",
        open_ports=[22], via="network_scan",
    )

    service = (
        await client.post(
            "/api/services",
            json={
                "name": "ssh",
                "service_type": "tcp",
                "device_id": device_id,
                "config": {"host": "192.168.1.50", "port": 22},
            },
        )
    ).json()
    assert service["device_vendor"] == "Raspberry Pi Trading Ltd"

    response = await client.get("/api/services")
    assert response.json()[0]["device_vendor"] == "Raspberry Pi Trading Ltd"

    response = await client.get(f"/api/services/{service['id']}")
    assert response.json()["device_vendor"] == "Raspberry Pi Trading Ltd"


@pytest.mark.asyncio
async def test_service_without_device_has_no_vendor(client: AsyncClient) -> None:
    response = await client.post(
        "/api/services",
        json={"name": "web", "service_type": "https", "config": {"url": "https://example.com"}},
    )
    assert response.json()["device_vendor"] is None
