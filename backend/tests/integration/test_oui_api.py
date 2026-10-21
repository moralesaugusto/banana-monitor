import httpx
import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.discovery.service import DiscoveryService

SAMPLE_CSV = (
    "Registry,Assignment,Organization Name,Organization Address\n"
    'MA-L,9C4E36,"Raspberry Pi Trading Ltd",Cambridge UK\n'
)


@pytest.mark.asyncio
async def test_oui_status_before_update_is_empty(client: AsyncClient) -> None:
    response = await client.get("/api/discovery/oui/status")
    assert response.status_code == 200
    assert response.json() == {"entry_count": 0, "updated_at": None}


@pytest.mark.asyncio
async def test_oui_update_populates_status_and_future_observations(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_download(timeout: float = 30.0) -> str:
        return SAMPLE_CSV

    monkeypatch.setattr("app.discovery.oui.download_oui_csv", fake_download)

    response = await client.post("/api/discovery/oui/update")
    assert response.status_code == 200
    body = response.json()
    assert body["entry_count"] == 1
    assert body["updated_at"] is not None

    status_response = await client.get("/api/discovery/oui/status")
    assert status_response.json()["entry_count"] == 1

    discovery_service = DiscoveryService(get_databases())
    await discovery_service.record_device_observation(
        network_id=None, ip="192.168.1.40", mac="9c:4e:36:aa:bb:cc", hostname=None,
        open_ports=[], via="network_scan",
    )
    candidates = (await client.get("/api/discovery/candidates?status=accepted")).json()
    assert candidates[0]["raw_attributes"]["vendor"] == "Raspberry Pi Trading Ltd"


@pytest.mark.asyncio
async def test_oui_update_failure_returns_502_not_500(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_download(timeout: float = 30.0) -> str:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr("app.discovery.oui.download_oui_csv", failing_download)

    response = await client.post("/api/discovery/oui/update")
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_device_detail_exposes_vendor_from_mac(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_download(timeout: float = 30.0) -> str:
        return SAMPLE_CSV

    monkeypatch.setattr("app.discovery.oui.download_oui_csv", fake_download)
    await client.post("/api/discovery/oui/update")

    discovery_service = DiscoveryService(get_databases())
    device_id = await discovery_service.record_device_observation(
        network_id=None, ip="192.168.1.41", mac="9c:4e:36:11:22:33", hostname="pi",
        open_ports=[22], via="network_scan",
    )

    detail = (await client.get(f"/api/devices/{device_id}")).json()
    assert detail["addresses"][0]["vendor"] == "Raspberry Pi Trading Ltd"
