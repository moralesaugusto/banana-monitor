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
        device_id=device_id,
        ip="10.0.0.5",
        port=443,
        service_type="https",
        source="scan",
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
        device_id=None,
        ip="10.0.0.7",
        port=8443,
        service_type="https",
        source="scan",
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
            Service(
                name="tcp 10.0.0.9:22",
                service_type="tcp",
                config={"host": "10.0.0.9", "port": 22},
                managed=False,
                port=22,
                source="scan",
                fingerprint={"product": "OpenSSH"},
            )
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
    assert [d["device_type"] for d in (await client.get("/api/devices")).json()] == ["platform_self"]
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


@pytest.mark.asyncio
async def test_start_from_scratch_clears_everything_but_login_audit_and_credentials(
    client: AsyncClient,
) -> None:
    import datetime

    from sqlalchemy import func, select

    from app.domain.enums import EntityType
    from app.domain.metrics_models import CheckResult, MetricSample
    from app.domain.models import (
        AiAgentMemory,
        AlertRule,
        AuditEntry,
        Event,
        HostFinding,
        LlmUsage,
        Network,
        Report,
        Site,
        TelegramConfig,
    )
    from app.knowledge.models import KnowledgeCollection, KnowledgeEntry

    databases = get_databases()
    network = (await client.post("/api/networks", json={"name": "Lab", "cidr": "10.0.0.0/24"})).json()
    device = (
        await client.post(
            "/api/devices",
            json={
                "display_name": "d",
                "device_type": "linux",
                "primary_ip": "10.0.0.5",
                "network_id": network["id"],
            },
        )
    ).json()
    config = {"host": "10.0.0.5", "port": 22}
    service = {"name": "s", "service_type": "tcp", "device_id": device["id"], "config": config}
    assert (await client.post("/api/services", json=service)).status_code == 201
    integration = {"integration_type": "custom_unregistered", "name": "i", "config": {"host": "10.0.0.5"}}
    assert (await client.post("/api/integrations", json=integration)).status_code == 201
    rule = {"name": "r", "condition_type": "device_down", "parameters": {"staleness_seconds": 90}}
    assert (await client.post("/api/alerts/rules", json=rule)).status_code == 201
    credential = {
        "label": "keep-me",
        "credential_type": "ssh_key",
        "secret": {"username": "u", "private_key": "k"},
    }
    assert (await client.post("/api/credentials", json=credential)).status_code == 201
    custom_agent = (await client.get("/api/ai-mode/agents")).json()[0]
    body = {k: custom_agent[k] for k in custom_agent if k not in ("id", "created_at", "updated_at")}
    body["name"] = "mine"
    assert (await client.post("/api/ai-mode/agents", json=body)).status_code in (200, 201)
    await client.put("/api/system/internet-access", json={"blocked": True})

    now = datetime.datetime.now(datetime.UTC)
    async with databases.app_session_factory() as session:
        session.add_all(
            [
                Event(source="t", category="c", message="m"),
                Report(title="r", content="c"),
                HostFinding(ip="10.0.0.5", kind="os", title="Debian"),
                AiAgentMemory(agent_name="bellaco", content="remember this"),
                LlmUsage(day="2026-11-18", source="agent", agent="a", provider="ollama", model="m"),
            ]
        )
        await session.commit()
        audit_before = await session.scalar(select(func.count()).select_from(AuditEntry))
    async with databases.metrics_session_factory() as session:
        session.add_all(
            [
                CheckResult(entity_type=EntityType.DEVICE, entity_id=1, ts=now, success=True),
                MetricSample(
                    entity_type=EntityType.DEVICE, entity_id=1, ts=now, metric_name="cpu", value=1.0
                ),
            ]
        )
        await session.commit()
    async with databases.knowledge_session_factory() as session:
        collection = KnowledgeCollection(name="Mine", description="")
        session.add(collection)
        await session.flush()
        session.add(KnowledgeEntry(collection_id=collection.id, title="t", content="c"))
        await session.commit()

    assert (await client.post("/api/system/reset", json={"confirm": "RESET"})).status_code == 200

    async def count(factory, model) -> int:  # noqa: ANN001
        async with factory() as session:
            return await session.scalar(select(func.count()).select_from(model)) or 0

    app, metrics, know = (
        databases.app_session_factory,
        databases.metrics_session_factory,
        databases.knowledge_session_factory,
    )
    for model in (Network, Report, HostFinding, AiAgentMemory, LlmUsage, AlertRule, TelegramConfig):
        assert await count(app, model) == 0, model.__name__
    for model in (CheckResult, MetricSample):
        assert await count(metrics, model) == 0, model.__name__
    assert await count(know, KnowledgeEntry) == 0
    async with know() as session:
        names = set(await session.scalars(select(KnowledgeCollection.name)))
    assert names == {"LAN notes", "Security knowledge", "Sandbox"}, "defaults only: my collection is gone"
    assert await count(app, Site) == 1
    assert (await client.get("/api/networks")).json() == []
    assert (await client.get("/api/services")).json() == []
    assert (await client.get("/api/integrations")).json() == []
    assert (await client.get("/api/alerts/rules")).json() == []
    assert [d["device_type"] for d in (await client.get("/api/devices")).json()] == ["platform_self"]
    agents = {a["name"] for a in (await client.get("/api/ai-mode/agents")).json()}
    assert "mine" not in agents and {"discoverer", "reviewer", "reporter"} <= agents
    assert (await client.get("/api/system/internet-access")).json()["blocked"] is False
    events = (await client.get("/api/events")).json()
    assert all(e["message"] != "m" for e in events)

    assert [c["label"] for c in (await client.get("/api/credentials")).json()] == ["keep-me"]
    assert (await client.get("/api/auth/me")).status_code == 200, "still signed in"
    assert await count(app, AuditEntry) >= audit_before
