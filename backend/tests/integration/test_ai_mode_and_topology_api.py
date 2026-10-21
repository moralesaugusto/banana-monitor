import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.session import get_databases
from app.discovery.service import DiscoveredServiceStore, DiscoveryService
from app.domain.models import AiMessage, AiMessageDelivery, AiRun, AiRunStep, Device


@pytest.mark.asyncio
async def test_ai_mode_settings_tools_and_gating(client: AsyncClient) -> None:
    settings = (await client.get("/api/ai-mode/settings")).json()
    assert settings["enabled"] is False and settings["max_iterations"] == 30

    updated = await client.put(
        "/api/ai-mode/settings",
        json={
            "enabled": True,
            "temperature": 0.7,
            "enabled_tools": ["run_nmap"],
            "system_prompt": "be brief",
        },
    )
    body = updated.json()
    assert body["enabled"] is True and body["temperature"] == 0.7 and body["system_prompt"] == "be brief"
    assert (await client.get("/api/system/discovery-settings")).json()["ai_mode_enabled"] is True

    bad = await client.put("/api/ai-mode/settings", json={"enabled_tools": ["rm_rf"]})
    assert bad.status_code == 422

    tools = (await client.get("/api/ai-mode/tools")).json()
    enabled = {t["name"]: t["enabled"] for t in tools["tools"]}
    assert enabled.pop("run_nmap") is True
    assert not any(enabled.values())
    assert {
        "run_nc",
        "record_service",
        "report_open_ports",
        "discover_hosts",
        "publish_message",
        "get_network_snapshot",
            "get_status_delta",
        "save_report",
        "web_search",
        "fetch_url",
        "virustotal_lookup",
        "list_inspect_targets",
        "ssh_readonly",
        "winrm_readonly",
        "proxmox_get",
        "http_inspect",
        "apply_updates",
        "submit_http_form",
    } == set(enabled)
    assert tools["guardrails"] and tools["default_system_prompt"]


@pytest.mark.asyncio
async def test_run_requires_enabled_and_lists_history(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    refused = await client.post("/api/ai-mode/runs", json={"targets": ["127.0.0.1"]})
    assert refused.status_code == 409

    await client.put("/api/ai-mode/settings", json={"enabled": True})

    async def fake_agent(databases: object, run_id: int) -> None:
        return None

    monkeypatch.setattr("app.api.routes.ai_mode.run_agent", fake_agent)
    started = await client.post("/api/ai-mode/runs", json={"targets": ["127.0.0.1"], "dry_run": True})
    assert started.status_code == 202
    run = started.json()
    assert run["status"] == "running" and run["dry_run"] is True
    assert run["entry_agent"] == "discoverer"  # default entry agent, surfaced for Run history to show

    again = await client.post("/api/ai-mode/runs", json={"targets": ["127.0.0.1"]})
    assert again.status_code == 409  # first is still marked running

    detail = (await client.get(f"/api/ai-mode/runs/{run['id']}")).json()
    assert detail["steps"] == [] and detail["system_prompt"]
    history = (await client.get("/api/ai-mode/runs")).json()
    assert len(history) == 1 and history[0]["entry_agent"] == "discoverer"
    assert (await client.get("/api/ai-mode/runs/999")).status_code == 404


@pytest.mark.asyncio
async def test_topology_links_network_device_and_service(client: AsyncClient) -> None:
    network = (await client.post("/api/networks", json={"name": "lan", "cidr": "10.0.0.0/24"})).json()
    databases = get_databases()
    device_id = await DiscoveryService(databases).record_device_observation(
        network_id=network["id"], ip="10.0.0.5", mac=None, hostname="nas", open_ports=[22], via="test"
    )
    await DiscoveredServiceStore(databases).upsert(
        device_id=device_id, ip="10.0.0.5", port=22, service_type="tcp", source="scan",
        fingerprint={"product": "OpenSSH", "version": "9.2", "source": "nmap"},
    )

    topo = (await client.get("/api/topology")).json()
    kinds = {n["id"]: n["kind"] for n in topo["nodes"]}
    assert kinds[f"network:{network['id']}"] == "network"
    assert kinds[f"device:{device_id}"] == "device"
    relations = {(e["source"], e["target"], e["relation"]) for e in topo["edges"]}
    assert (f"network:{network['id']}", f"device:{device_id}", "contains") in relations
    service_node = next(n for n in topo["nodes"] if n["kind"] == "service")
    assert service_node["subtitle"] == "OpenSSH 9.2"

    no_services = (await client.get("/api/topology?include_services=false")).json()
    assert all(n["kind"] != "service" for n in no_services["nodes"])


@pytest.mark.asyncio
async def test_reset_returns_ai_mode_to_defaults(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_agent(databases: object, run_id: int) -> None:
        return None

    monkeypatch.setattr("app.api.routes.ai_mode.run_agent", fake_agent)
    await client.put(
        "/api/ai-mode/settings",
        json={"enabled": True, "temperature": 0.9, "system_prompt": "custom", "enabled_tools": ["run_nc"]},
    )
    schedule = {
        "schedule_enabled": True, "schedule_interval_seconds": 3600, "schedule_entry_agent": "reviewer",
    }
    await client.put("/api/ai-mode/schedule", json=schedule)
    agents = (await client.get("/api/ai-mode/agents")).json()
    await client.delete(f"/api/ai-mode/agents/{agents[-1]['id']}")
    tool = {"name": "whatweb", "description": "d", "kind": "command", "command": ["whatweb", "{target}"]}
    await client.post("/api/ai-mode/custom-tools", json=tool)
    await client.post("/api/ai-mode/guardrails", json={"name": "g", "kind": "deny_regex", "pattern": "x"})
    run = (await client.post("/api/ai-mode/runs", json={"targets": ["127.0.0.1"], "dry_run": True})).json()

    blocked = await client.post("/api/ai-mode/reset")
    assert blocked.status_code == 409

    async with get_databases().app_session_factory() as session:
        (await session.get(AiRun, run["id"])).status = "done"  # type: ignore[union-attr]
        session.add(AiRunStep(run_id=run["id"], idx=0, kind="llm", request={}, response={}))
        session.add(AiMessage(run_id=run["id"], topic="t", sender="s", correlation_id="c"))
        await session.commit()

    assert (await client.post("/api/ai-mode/reset")).status_code == 204

    settings = (await client.get("/api/ai-mode/settings")).json()
    assert settings["enabled"] is False and settings["temperature"] == 0.2 and settings["system_prompt"] == ""
    assert settings["enabled_tools"] == ["run_nmap", "run_nc", "report_open_ports", "discover_hosts"]
    assert (await client.get("/api/ai-mode/schedule")).json()["schedule_enabled"] is False
    assert (await client.get("/api/ai-mode/runs")).json() == []
    # tajonaso's 150 HexStrike tools are themselves a seeded default and come back; the manually
    # created "whatweb" tool does not.
    tool_names = {t["name"] for t in (await client.get("/api/ai-mode/custom-tools")).json()}
    assert "whatweb" not in tool_names and "nmap_scan" in tool_names
    assert (await client.get("/api/ai-mode/guardrails")).json() == []
    agents_after = (await client.get("/api/ai-mode/agents")).json()
    names = [a["name"] for a in agents_after]
    assert names == ["discoverer", "reviewer", "reporter", "bellaco", "sinverguenza", "tajonaso"]
    discoverer = next(a for a in agents_after if a["name"] == "discoverer")
    assert discoverer["display_name"] == "Master Discoverer"
    async with get_databases().app_session_factory() as session:
        for model in (AiRunStep, AiMessage, AiMessageDelivery):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.asyncio
async def test_default_agent_enable_is_independent_of_global_ai_mode_switch(client: AsyncClient) -> None:
    """Disabling the seeded `discoverer` (Master Discoverer) must not stop other agents from being
    scheduled, and the global 'Enable AI Mode' switch gates every agent equally, not just the default one."""
    agents = (await client.get("/api/ai-mode/agents")).json()
    discoverer = next(a for a in agents if a["name"] == "discoverer")
    assert discoverer["display_name"] == "Master Discoverer"

    await client.put(f"/api/ai-mode/agents/{discoverer['id']}", json={**discoverer, "enabled": False})
    schedule = {"schedule_enabled": True, "schedule_entry_agent": "reviewer"}
    await client.put("/api/ai-mode/schedule", json=schedule)
    await client.put("/api/ai-mode/settings", json={"enabled": True})

    status = (await client.get("/api/ai-mode/status")).json()
    by_name = {a["name"]: a for a in status["agents"]}
    assert by_name["discoverer"]["state"] == "disabled"
    assert by_name["reviewer"]["state"] == "scheduled"

    await client.put("/api/ai-mode/settings", json={"enabled": False})
    status = (await client.get("/api/ai-mode/status")).json()
    by_name = {a["name"]: a for a in status["agents"]}
    # global switch off: no agent is scheduled, enabled or not
    assert by_name["reviewer"]["state"] == "stopped"
    assert by_name["discoverer"]["state"] == "disabled"


async def test_status_reports_the_llm_activity_while_a_model_call_is_in_flight(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """status.agents[].activity distinguishes "waiting on the model" from the coarser "working" state -
    see orchestrator.py's ctx.set_state(cfg.name, "llm")."""
    import asyncio

    from app.llm.agent import create_run
    from app.llm.orchestrator import run_agent

    holding = asyncio.Event()
    release = asyncio.Event()

    async def fake(**kwargs: object) -> dict:
        holding.set()
        await release.wait()
        return {"choices": [{"message": {"content": "ok", "reasoning": None}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    await client.put("/api/ai-mode/settings", json={"enabled": True})
    run_id = await create_run(get_databases(), ["10.0.0.1"], False)
    task = asyncio.create_task(run_agent(get_databases(), run_id))
    await asyncio.wait_for(holding.wait(), 5)

    status = (await client.get("/api/ai-mode/status")).json()
    by_name = {a["name"]: a for a in status["agents"]}
    assert by_name["discoverer"]["state"] == "working"
    assert by_name["discoverer"]["activity"] == "llm"

    release.set()
    await asyncio.wait_for(task, 5)


async def test_agent_workflow_patch_moves_and_toggles_without_touching_the_rest(client: AsyncClient) -> None:
    agents = (await client.get("/api/ai-mode/agents")).json()
    reviewer = next(a for a in agents if a["name"] == "reviewer")
    patched = await client.patch(
        f"/api/ai-mode/agents/{reviewer['id']}/workflow",
        json={"workflow_x": 120.5, "workflow_y": 40, "enabled": False},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert (body["workflow_x"], body["workflow_y"], body["enabled"]) == (120.5, 40, False)
    assert body["system_prompt"] == reviewer["system_prompt"]

    # A full edit from the form (which does not know the canvas position) keeps the position.
    form = {k: v for k, v in body.items() if k not in ("id", "workflow_x", "workflow_y")}
    kept = (await client.put(f"/api/ai-mode/agents/{reviewer['id']}", json=form)).json()
    assert (kept["workflow_x"], kept["workflow_y"]) == (120.5, 40)


async def test_bus_route_reports_who_receives_and_who_may_publish(client: AsyncClient) -> None:
    await client.get("/api/ai-mode/agents")  # seeds the default agents
    route = (await client.get("/api/ai-mode/bus/route", params={"topic": "result.bellaco"})).json()
    assert route["valid"] is True
    assert [(s["agent"], s["pattern"]) for s in route["subscribers"]] == [("reporter", "result.bellaco")]
    # discoverer and reporter may both publish result.#
    assert {p["agent"] for p in route["publishers"]} >= {"discoverer", "reporter"}
    assert {p["pattern"] for p in route["publishers"]} == {"result.#"}

    nobody = (await client.get("/api/ai-mode/bus/route", params={"topic": "no.such.topic"})).json()
    assert nobody["valid"] is True and nobody["subscribers"] == [] and nobody["publishers"] == []

    for bad in ("", "result.*", "Bad Topic", "a.#"):
        assert (await client.get("/api/ai-mode/bus/route", params={"topic": bad})).json()["valid"] is False


async def test_bus_overview_counts_traffic_per_topic_and_run(client: AsyncClient) -> None:
    await client.get("/api/ai-mode/agents")
    async with get_databases().app_session_factory() as session:
        runs = []
        for _ in range(2):
            run = AiRun(
                targets=[], dry_run=True, model="m", base_url="", system_prompt="", settings_snapshot={}
            )
            session.add(run)
            runs.append(run)
        await session.flush()

        def message(
            run: AiRun, topic: str, sender: str, status: str, deliveries: list[tuple[str, str]]
        ) -> None:
            session.add(
                AiMessage(
                    run_id=run.id, topic=topic, sender=sender, correlation_id="c", status=status,
                    deliveries=[AiMessageDelivery(recipient=r, state=s) for r, s in deliveries],
                )
            )

        message(runs[0], "task.discoverer", "human", "delivered", [("discoverer", "acked")])
        message(runs[0], "result.discoverer", "discoverer", "delivered", [("reporter", "acked")])
        message(runs[0], "result.discoverer", "discoverer", "held", [("reporter", "pending")])
        message(runs[0], "approval.tool.bellaco", "bellaco", "held", [])
        message(runs[1], "result.discoverer", "discoverer", "delivered", [("reporter", "dropped")])
        await session.commit()
        first, second = runs[0].id, runs[1].id

    one = (await client.get("/api/ai-mode/bus/overview", params={"run_id": first})).json()
    by_topic = {t["topic"]: t for t in one["topics"]}
    # approval prompts are not routed traffic
    assert set(by_topic) == {"task.discoverer", "result.discoverer"}
    assert one["total_messages"] == 3 and one["run_id"] == first
    result = by_topic["result.discoverer"]
    assert (result["messages"], result["held"]) == (2, 1)
    assert result["publishers"] == ["discoverer"] and result["recipients"] == ["reporter"]
    assert result["deliveries"] == {"acked": 1, "pending": 1}

    every = (await client.get("/api/ai-mode/bus/overview")).json()
    assert every["run_id"] is None and every["total_messages"] == 4
    assert {t["topic"]: t for t in every["topics"]}["result.discoverer"]["deliveries"] == {
        "acked": 1, "pending": 1, "dropped": 1,
    }
    other = (await client.get("/api/ai-mode/bus/overview", params={"run_id": second})).json()
    assert other["total_messages"] == 1


async def test_bus_health_reports_limits_held_approvals_and_problems(client: AsyncClient) -> None:
    import datetime

    from app.domain.models import utcnow

    await client.get("/api/ai-mode/agents")
    async with get_databases().app_session_factory() as session:
        run = AiRun(
            targets=[], dry_run=True, model="m", base_url="", system_prompt="",
            settings_snapshot={"max_run_seconds": 600}, finished_at=utcnow(),
        )
        run.started_at = utcnow() - datetime.timedelta(seconds=150)
        session.add(run)
        await session.flush()
        old = utcnow() - datetime.timedelta(seconds=700)
        session.add_all(
            [
                AiMessage(run_id=run.id, topic="task.discoverer", sender="human", correlation_id="c", hops=0),
                AiMessage(
                    run_id=run.id, topic="result.discoverer", sender="discoverer", correlation_id="c", hops=3,
                    deliveries=[AiMessageDelivery(recipient="reporter", state="dropped")],
                ),
                AiMessage(
                    run_id=run.id, topic="result.reviewer", sender="reviewer", correlation_id="c", hops=2,
                    status="held", ts=old,
                ),
                AiMessage(
                    run_id=run.id, topic="approval.tool.bellaco", sender="bellaco", correlation_id="c",
                    status="held",
                ),
                AiMessage(
                    run_id=run.id, topic="result.bellaco", sender="bellaco", correlation_id="c",
                    status="rejected", note="too broad",
                ),
            ]
        )
        await session.commit()
        run_id = run.id

    health = (await client.get("/api/ai-mode/bus/health", params={"run_id": run_id})).json()
    assert health["active"] is False
    assert health["messages"] == {"used": 4, "limit": 500}  # approval prompts are not counted
    assert health["hops"] == {"used": 3, "limit": 8}
    assert health["seconds"]["limit"] == 600 and 140 < health["seconds"]["used"] < 200
    assert {(h["topic"], h["overdue"]) for h in health["held"]} == {
        ("result.reviewer", True), ("approval.tool.bellaco", False),
    }
    by_agent = {a["name"]: a for a in health["agents"]}
    assert by_agent["reviewer"]["held"] == 1 and by_agent["bellaco"]["held"] == 1
    assert by_agent["reporter"]["dropped"] == 1
    assert {(p["kind"], p["reason"]) for p in health["problems"]} == {
        ("rejected", "too broad"), ("dropped", "reporter was stopped before it handled this message"),
    }
    assert (await client.get("/api/ai-mode/bus/health", params={"run_id": 99999})).status_code == 404


@pytest.mark.asyncio
async def test_run_without_known_devices_needs_a_network_and_then_finds_hosts_itself(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.put("/api/ai-mode/settings", json={"enabled": True})

    async def fake_agent(databases: object, run_id: int) -> None:
        return None

    monkeypatch.setattr("app.api.routes.ai_mode.run_agent", fake_agent)
    nothing = await client.post("/api/ai-mode/runs", json={})
    assert nothing.status_code == 400 and "no network" in nothing.json()["detail"]

    await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.1.0/24"})
    started = await client.post("/api/ai-mode/runs", json={})
    assert started.status_code == 202
    detail = (await client.get(f"/api/ai-mode/runs/{started.json()['id']}")).json()
    assert detail["targets"] == []
    assert detail["settings_snapshot"]["networks"][0]["cidr"] == "192.168.1.0/24"


@pytest.mark.asyncio
async def test_deleting_a_network_drops_its_devices_out_of_auto_selected_targets(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: a user reported that deleting (or adding) a network had no effect on what
    a manual Start with no explicit targets picks up. Root cause: the auto-selected target list was
    not scoped by network at all, so a device whose network was deleted (devices are kept, only
    unassigned - see networks.py's delete_network) kept being targeted forever."""
    await client.put("/api/ai-mode/settings", json={"enabled": True})

    async def fake_agent(databases: object, run_id: int) -> None:
        return None

    monkeypatch.setattr("app.api.routes.ai_mode.run_agent", fake_agent)

    network = (await client.post("/api/networks", json={"name": "lan", "cidr": "10.0.0.0/24"})).json()
    await client.post("/api/networks", json={"name": "other", "cidr": "10.0.1.0/24"})  # stays around
    databases = get_databases()
    device_id = await DiscoveryService(databases).record_device_observation(
        network_id=network["id"], ip="10.0.0.5", mac=None, hostname="nas", open_ports=[22], via="test"
    )

    started = await client.post("/api/ai-mode/runs", json={})
    assert started.status_code == 202
    detail = (await client.get(f"/api/ai-mode/runs/{started.json()['id']}")).json()
    assert detail["targets"] == ["10.0.0.5"]

    await client.delete(f"/api/networks/{network['id']}")
    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        assert device is not None and device.network_id is None  # kept, just unassigned
        run = await session.get(AiRun, started.json()["id"])
        run.status = "done"  # the fake orchestrator never marks it finished; simulate that it did
        await session.commit()

    started_again = await client.post("/api/ai-mode/runs", json={})
    assert started_again.status_code == 202
    detail_again = (await client.get(f"/api/ai-mode/runs/{started_again.json()['id']}")).json()
    assert detail_again["targets"] == []  # the unassigned device is no longer auto-selected


@pytest.mark.asyncio
async def test_model_call_timeouts_are_tunable_per_agent_and_by_default(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.put("/api/ai-mode/settings", json={"enabled": True, "llm_call_timeout_seconds": 900})
    assert (await client.get("/api/ai-mode/settings")).json()["llm_call_timeout_seconds"] == 900
    too_low = await client.put("/api/ai-mode/settings", json={"llm_call_timeout_seconds": 5})
    assert too_low.status_code == 422

    agents = (await client.get("/api/ai-mode/agents")).json()
    slow = {k: v for k, v in agents[0].items() if k != "id"} | {"llm_timeout_seconds": 600}
    updated = await client.put(f"/api/ai-mode/agents/{agents[0]['id']}", json=slow)
    assert updated.json()["llm_timeout_seconds"] == 600

    async def fake_agent(databases: object, run_id: int) -> None:
        return None

    monkeypatch.setattr("app.api.routes.ai_mode.run_agent", fake_agent)
    run = (await client.post("/api/ai-mode/runs", json={"targets": ["127.0.0.1"]})).json()
    snapshot = (await client.get(f"/api/ai-mode/runs/{run['id']}")).json()["settings_snapshot"]
    assert snapshot["llm_timeout_seconds"] == 900
    assert {a["name"]: a["llm_timeout_seconds"] for a in snapshot["agents"]}[agents[0]["name"]] == 600


async def test_llm_concurrency_caps_are_tunable_bounded_and_snapshotted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    defaults = (await client.get("/api/ai-mode/settings")).json()
    assert defaults["ollama_max_concurrent_calls"] == 2
    assert defaults["openrouter_max_concurrent_calls"] == 4

    updated = await client.put(
        "/api/ai-mode/settings",
        json={"enabled": True, "ollama_max_concurrent_calls": 1, "openrouter_max_concurrent_calls": 8},
    )
    assert updated.json()["ollama_max_concurrent_calls"] == 1
    assert updated.json()["openrouter_max_concurrent_calls"] == 8

    too_low = await client.put("/api/ai-mode/settings", json={"ollama_max_concurrent_calls": 0})
    assert too_low.status_code == 422
    too_high = await client.put("/api/ai-mode/settings", json={"openrouter_max_concurrent_calls": 17})
    assert too_high.status_code == 422

    async def fake_agent(databases: object, run_id: int) -> None:
        return None

    monkeypatch.setattr("app.api.routes.ai_mode.run_agent", fake_agent)
    run = (await client.post("/api/ai-mode/runs", json={"targets": ["127.0.0.1"]})).json()
    snapshot = (await client.get(f"/api/ai-mode/runs/{run['id']}")).json()["settings_snapshot"]
    assert snapshot["ollama_max_concurrent_calls"] == 1
    assert snapshot["openrouter_max_concurrent_calls"] == 8
