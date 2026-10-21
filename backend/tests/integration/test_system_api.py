import asyncio

import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.discovery.service import DiscoveredServiceStore, DiscoveryService


@pytest.mark.asyncio
async def test_discovery_settings_default_and_update(client: AsyncClient) -> None:
    response = await client.get("/api/system/discovery-settings")
    assert response.status_code == 200
    body = response.json()
    assert body["scan_mode"] == "auto"
    assert body["timing_template"] == 4
    assert body["ai_mode_enabled"] is False

    response = await client.put(
        "/api/system/discovery-settings", json={"scan_mode": "manual", "timing_template": 5}
    )
    assert response.status_code == 200
    assert response.json()["scan_mode"] == "manual"
    assert (await client.get("/api/system/discovery-settings")).json()["timing_template"] == 5

    bad = await client.put("/api/system/discovery-settings", json={"timing_template": 9})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_scan_all_returns_immediately(client: AsyncClient) -> None:
    response = await client.post("/api/system/scan-all")
    assert response.status_code == 202
    await asyncio.sleep(0)
    assert (await client.get("/api/system/scan-status")).status_code == 200


@pytest.mark.asyncio
async def test_discovered_services_are_unmanaged_and_filterable(client: AsyncClient) -> None:
    databases = get_databases()
    device_id = await DiscoveryService(databases).record_device_observation(
        network_id=None, ip="10.0.0.5", mac=None, hostname="nas", open_ports=[22, 443], via="test"
    )
    store = DiscoveredServiceStore(databases)
    await store.upsert(
        device_id=device_id, ip="10.0.0.5", port=443, service_type="https", source="scan",
        fingerprint={"name": "http", "product": "nginx", "source": "nmap"},
    )
    await store.upsert(device_id=device_id, ip="10.0.0.5", port=22, service_type="tcp", source="scan")
    await store.upsert(device_id=device_id, ip="10.0.0.5", port=22, service_type="tcp", source="scan")

    rows = (await client.get("/api/services")).json()
    assert len(rows) == 2
    assert all(r["managed"] is False and r["source"] == "scan" for r in rows)

    by_port = (await client.get("/api/services?sort=port&order=desc")).json()
    assert [r["port"] for r in by_port] == [443, 22]

    nginx = (await client.get("/api/services?q=nginx")).json()
    assert [r["port"] for r in nginx] == [443]
    assert (await client.get("/api/services?service_type=tcp")).json()[0]["port"] == 22
    assert (await client.get("/api/services?managed=true")).json() == []

    promoted = await client.patch(f"/api/services/{nginx[0]['id']}", json={"managed": True})
    assert promoted.json()["managed"] is True


@pytest.mark.asyncio
async def test_scan_fingerprints_preexisting_service_after_port_backfill(client: AsyncClient) -> None:
    created = await client.post(
        "/api/services",
        json={"name": "10.0.0.7:8443", "service_type": "https", "config": {"url": "https://10.0.0.7:8443"}},
    )
    assert created.json()["port"] is None

    databases = get_databases()
    store = DiscoveredServiceStore(databases)
    assert await store.reconcile() == 1
    await store.upsert(
        device_id=None, ip="10.0.0.7", port=8443, service_type="https", source="scan",
        fingerprint={"name": "http", "product": "nginx", "source": "nmap"},
    )

    rows = (await client.get("/api/services")).json()
    assert len(rows) == 1  # matched the existing row instead of duplicating it
    assert rows[0]["port"] == 8443 and rows[0]["managed"] is True
    assert rows[0]["fingerprint"]["product"] == "nginx"


@pytest.mark.asyncio
async def test_bulk_service_actions(client: AsyncClient) -> None:
    ids = []
    for port in (1, 2, 3):
        r = await client.post(
            "/api/services",
            json={"name": f"s{port}", "service_type": "tcp", "config": {"host": "h", "port": port}},
        )
        ids.append(r.json()["id"])

    r = await client.post("/api/services/bulk", json={"ids": ids[:2], "action": "unmonitor"})
    assert r.json() == {"affected": 2}
    assert len((await client.get("/api/services?managed=false")).json()) == 2

    r = await client.post("/api/services/bulk", json={"ids": [*ids, 999], "action": "delete"})
    assert r.json() == {"affected": 3}
    assert (await client.get("/api/services")).json() == []


@pytest.mark.asyncio
async def test_reconcile_links_orphans_and_merges_scan_duplicates(client: AsyncClient) -> None:
    databases = get_databases()
    device_id = await DiscoveryService(databases).record_device_observation(
        network_id=None, ip="10.0.0.9", mac=None, hostname=None, open_ports=[22], via="test"
    )
    manual = await client.post(
        "/api/services",
        json={"name": "10.0.0.9:22", "service_type": "tcp", "config": {"host": "10.0.0.9", "port": 22}},
    )
    store = DiscoveredServiceStore(databases)
    # a scan-created duplicate that carries the fingerprint, with no device link
    from app.domain.models import Service

    async with databases.app_session_factory() as session:
        session.add(
            Service(name="tcp 10.0.0.9:22", service_type="tcp", config={"host": "10.0.0.9", "port": 22},
                    managed=False, port=22, source="scan", fingerprint={"product": "OpenSSH"})
        )
        await session.commit()

    assert await store.reconcile() >= 2
    rows = (await client.get("/api/services")).json()
    assert len(rows) == 1
    assert rows[0]["id"] == manual.json()["id"] and rows[0]["device_id"] == device_id
    assert rows[0]["fingerprint"]["product"] == "OpenSSH"


@pytest.mark.asyncio
async def test_reset_requires_confirmation_and_clears_inventory(client: AsyncClient) -> None:
    device = (await client.post("/api/devices", json={"display_name": "d", "device_type": "other"})).json()
    config = {"host": "10.0.0.2", "port": 22}
    service = {"name": "s", "service_type": "tcp", "device_id": device["id"], "config": config}
    assert (await client.post("/api/services", json=service)).status_code == 201

    assert (await client.post("/api/system/reset", json={"confirm": "no"})).status_code == 400
    response = await client.post("/api/system/reset", json={"confirm": "RESET"})
    assert response.json() == {"devices": 1, "services": 1}
    assert (await client.get("/api/devices")).json() == []
    assert (await client.get("/api/services")).json() == []


@pytest.mark.asyncio
async def test_internet_access_status_and_kill_switch(client: AsyncClient) -> None:
    status = (await client.get("/api/system/internet-access")).json()
    assert status == {"blocked": False, "agents": []}

    agents = (await client.get("/api/ai-mode/agents")).json()
    agent = agents[0]
    body = {k: agent[k] for k in agent if k not in ("id", "created_at", "updated_at")}
    body["enabled_tools"] = [*body["enabled_tools"], "web_search"]
    assert (await client.put(f"/api/ai-mode/agents/{agent['id']}", json=body)).status_code == 200
    assert (await client.get("/api/system/internet-access")).json()["agents"] == [agent["name"]]

    await client.put("/api/system/internet-access", json={"blocked": True})
    assert (await client.get("/api/system/internet-access")).json()["blocked"] is True

    # An AI Mode reset must not clear the kill switch.
    assert (await client.post("/api/ai-mode/reset")).status_code == 204
    assert (await client.get("/api/system/internet-access")).json()["blocked"] is True


@pytest.mark.asyncio
async def test_kill_switch_blocks_web_tools(client: AsyncClient) -> None:
    from app.llm import agent_tools

    await client.put("/api/system/internet-access", json={"blocked": True})
    for name, args in (("web_search", {"query": "x"}), ("fetch_url", {"url": "https://example.com"})):
        with pytest.raises(agent_tools.AgentToolError, match="kill switch"):
            await agent_tools.dispatch(get_databases(), name, args, enabled=[name])


@pytest.mark.asyncio
async def test_discovery_settings_cannot_touch_kill_switch(client: AsyncClient) -> None:
    await client.put("/api/system/discovery-settings", json={"agent_internet_blocked": True})
    assert (await client.get("/api/system/internet-access")).json()["blocked"] is False
