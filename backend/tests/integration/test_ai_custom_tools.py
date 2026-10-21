from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.domain.models import AiCustomTool, AiGuardrail
from app.llm import custom_tools
from app.llm.agent_tools import AgentToolError

COMMAND_TOOL = {
    "name": "whatweb_scan",
    "description": "Identify a web server",
    "kind": "command",
    "command": ["whatweb", "{target}"],
}


@pytest.mark.asyncio
async def test_custom_tool_crud(client: AsyncClient) -> None:
    created = await client.post("/api/ai-mode/custom-tools", json=COMMAND_TOOL)
    assert created.status_code == 201
    tool_id = created.json()["id"]

    assert (await client.post("/api/ai-mode/custom-tools", json=COMMAND_TOOL)).status_code == 409
    builtin = {**COMMAND_TOOL, "name": "run_nmap"}
    assert (await client.post("/api/ai-mode/custom-tools", json=builtin)).status_code == 409
    empty = {**COMMAND_TOOL, "name": "bad", "command": []}
    assert (await client.post("/api/ai-mode/custom-tools", json=empty)).status_code == 422

    renamed = {**COMMAND_TOOL, "description": "New"}
    updated = await client.put(f"/api/ai-mode/custom-tools/{tool_id}", json=renamed)
    assert updated.json()["description"] == "New"

    enabled = {"enabled_tools": ["run_nmap", "whatweb_scan"]}
    settings = await client.put("/api/ai-mode/settings", json=enabled)
    assert settings.status_code == 200

    assert (await client.delete(f"/api/ai-mode/custom-tools/{tool_id}")).status_code == 204
    remaining = {t["name"] for t in (await client.get("/api/ai-mode/custom-tools")).json()}
    assert "whatweb_scan" not in remaining  # tajonaso's own seeded tools are unrelated and stay
    assert "whatweb_scan" not in (await client.get("/api/ai-mode/settings")).json()["enabled_tools"]


@pytest.mark.asyncio
async def test_guardrail_crud_rejects_bad_regex(client: AsyncClient) -> None:
    rule = {"name": "no-admin-ports", "kind": "deny_regex", "pattern": "^(22|3389)$"}
    created = await client.post("/api/ai-mode/guardrails", json=rule)
    assert created.status_code == 201
    assert (await client.post("/api/ai-mode/guardrails", json={**rule, "pattern": "("})).status_code == 422

    rule_id = created.json()["id"]
    disabled = await client.put(f"/api/ai-mode/guardrails/{rule_id}", json={**rule, "enabled": False})
    assert disabled.json()["enabled"] is False
    assert (await client.delete(f"/api/ai-mode/guardrails/{rule_id}")).status_code == 204
    assert (await client.delete(f"/api/ai-mode/guardrails/{rule_id}")).status_code == 404


@pytest.mark.asyncio
async def test_command_tool_runs_without_shell_and_obeys_guardrails(client: AsyncClient) -> None:
    tool = AiCustomTool(**COMMAND_TOOL, parameters={})
    deny = AiGuardrail(name="no-3389", kind="deny_regex", pattern="^3389$", enabled=True)
    databases = get_databases()
    with patch.object(custom_tools, "_run", AsyncMock(return_value={"exit_code": 0, "output": "ok"})) as run:
        args = {"target": "127.0.0.1", "port": 80}
        result = await custom_tools.run_custom_tool(databases, tool, [deny], args)
        assert result["output"] == "ok"
        run.assert_awaited_once()
        assert run.await_args.args[0] == ["whatweb", "127.0.0.1"]

        with pytest.raises(AgentToolError, match="guardrail"):
            blocked = {"target": "127.0.0.1", "port": 3389}
            await custom_tools.run_custom_tool(databases, tool, [deny], blocked)
        with pytest.raises(AgentToolError, match="not inside"):
            await custom_tools.run_custom_tool(databases, tool, [], {"target": "8.8.8.8"})


@pytest.mark.asyncio
async def test_agents_are_seeded_and_validated(client: AsyncClient) -> None:
    agents = (await client.get("/api/ai-mode/agents")).json()
    assert [a["name"] for a in agents] == [
        "discoverer", "reviewer", "reporter", "bellaco", "sinverguenza", "tajonaso"
    ]
    assert agents[1]["subscribes"] == ["discovery.ports.found", "human.reviewer"]

    body = {"name": "summarizer", "subscribes": ["result.#"], "enabled_tools": ["publish_message"]}
    created = await client.post("/api/ai-mode/agents", json=body)
    assert created.status_code == 201
    assert (await client.post("/api/ai-mode/agents", json=body)).status_code == 409
    bad_pattern = {**body, "name": "x2", "subscribes": ["a.#.b"]}
    assert (await client.post("/api/ai-mode/agents", json=bad_pattern)).status_code == 422
    bad_tool = {**body, "name": "x3", "enabled_tools": ["rm"]}
    assert (await client.post("/api/ai-mode/agents", json=bad_tool)).status_code == 422

    agent_id = created.json()["id"]
    updated = await client.put(f"/api/ai-mode/agents/{agent_id}", json={**body, "require_approval": "both"})
    assert updated.json()["require_approval"] == "both"
    assert (await client.delete(f"/api/ai-mode/agents/{agent_id}")).status_code == 204


@pytest.mark.asyncio
async def test_message_endpoints_require_an_active_run(client: AsyncClient) -> None:
    assert (await client.get("/api/ai-mode/messages")).json() == []
    human = {"run_id": 1, "topic": "task.discoverer", "text": "hi"}
    assert (await client.post("/api/ai-mode/messages", json=human)).status_code == 409
    assert (await client.post("/api/ai-mode/messages/5/approve", json={})).status_code == 404
    assert (await client.post("/api/ai-mode/runs/1/pause")).status_code == 409


@pytest.mark.asyncio
async def test_run_over_the_api_logs_bus_messages(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    await client.put("/api/ai-mode/settings", json={"enabled": True})
    # Every seeded agent but discoverer now reacts to its result (reviewer via discovery.ports.found,
    # the rest via result.discoverer) - disable them all so only discoverer runs.
    agents = (await client.get("/api/ai-mode/agents")).json()
    for agent in agents:
        if agent["name"] != "discoverer":
            await client.put(f"/api/ai-mode/agents/{agent['id']}", json={**agent, "enabled": False})

    async def fake(**kwargs: object) -> dict:
        return {"choices": [{"message": {"content": "Nothing to report.", "reasoning": None}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    started = await client.post("/api/ai-mode/runs", json={"targets": ["127.0.0.1"]})
    assert started.status_code == 202
    run_id = started.json()["id"]

    for _ in range(100):
        run = (await client.get(f"/api/ai-mode/runs/{run_id}")).json()
        if run["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert run["status"] == "done" and run["summary"] == "Nothing to report."

    messages = (await client.get(f"/api/ai-mode/messages?run_id={run_id}")).json()
    assert [(m["topic"], m["sender"]) for m in messages] == [
        ("task.discoverer", "human"),
        ("result.discoverer", "discoverer"),
    ]
    assert messages[0]["deliveries"] == [{"recipient": "discoverer", "state": "acked"}]
    assert {s["agent"] for s in run["steps"]} == {"discoverer"}


@pytest.mark.asyncio
async def test_agent_can_use_its_own_ollama_host_and_models_can_be_listed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    body = {"name": "remote", "base_url": "http://10.0.0.9:11434/v1", "model_override": "qwen3:8b"}
    created = await client.post("/api/ai-mode/agents", json=body)
    assert created.json()["base_url"] == "http://10.0.0.9:11434/v1"
    bad = {**body, "name": "bad", "base_url": "ftp://x"}
    assert (await client.post("/api/ai-mode/agents", json=bad)).status_code == 422

    original = httpx.AsyncClient.get

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        if not str(url).startswith("http://10.0.0.9"):
            return await original(self, url, **kwargs)  # type: ignore[arg-type]  # the test client itself
        assert url == "http://10.0.0.9:11434/v1/models"
        payload = {"data": [{"id": "b"}, {"id": "a"}]}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    listed = await client.get("/api/ai-mode/ollama-models", params={"base_url": "http://10.0.0.9:11434/v1"})
    assert listed.json()["models"] == ["a", "b"]
    assert (await client.get("/api/ai-mode/ollama-models", params={"base_url": "nope"})).status_code == 422


@pytest.mark.asyncio
async def test_schedule_settings_and_agent_status(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    status = (await client.get("/api/ai-mode/status")).json()
    assert status["run"] is None and status["schedule"]["schedule_enabled"] is False
    states = {a["name"]: a["state"] for a in status["agents"]}
    assert states == {
        n: "stopped"
        for n in ("discoverer", "reviewer", "reporter", "bellaco", "sinverguenza", "tajonaso")
    }

    bad = await client.put("/api/ai-mode/schedule", json={"schedule_interval_seconds": 1})
    assert bad.status_code == 422
    nobody = await client.put("/api/ai-mode/schedule", json={"schedule_entry_agent": "nobody"})
    assert nobody.status_code == 422
    updated = await client.put(
        "/api/ai-mode/schedule",
        json={"schedule_enabled": True, "schedule_interval_seconds": 1800, "max_run_minutes": 10},
    )
    assert updated.json()["next_run_at"] is not None and updated.json()["max_run_minutes"] == 10

    status = (await client.get("/api/ai-mode/status")).json()
    assert {a["state"] for a in status["agents"]} == {"stopped"}  # AI Mode itself is still off
    await client.put("/api/ai-mode/settings", json={"enabled": True})
    status = (await client.get("/api/ai-mode/status")).json()
    assert {a["state"] for a in status["agents"]} == {"scheduled"}

    async def slow(**kwargs: object) -> dict:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", slow)
    started = (await client.post("/api/ai-mode/runs", json={"targets": ["127.0.0.1"]})).json()
    for _ in range(100):
        status = (await client.get("/api/ai-mode/status")).json()
        if status["run"] and any(a["state"] == "working" for a in status["agents"]):
            break
        await asyncio.sleep(0.02)
    assert status["run"]["id"] == started["id"] and status["run"]["started_by"] == "manual"
    states = {a["name"]: a["state"] for a in status["agents"]}
    assert states == {
        "discoverer": "working",
        **{n: "waiting" for n in ("reviewer", "reporter", "bellaco", "sinverguenza", "tajonaso")},
    }
    assert status["run"]["deadline_at"] > status["run"]["started_at"]

    assert (await client.post(f"/api/ai-mode/runs/{started['id']}/stop")).status_code == 202
    for _ in range(100):
        if (await client.get("/api/ai-mode/status")).json()["run"] is None:
            break
        await asyncio.sleep(0.02)
    last = (await client.get("/api/ai-mode/status")).json()["last_run"]
    assert last["stop_reason"] == "manual"


@pytest.mark.asyncio
async def test_settings_toggle_does_not_overwrite_agent_edits(client: AsyncClient) -> None:
    agents = (await client.get("/api/ai-mode/agents")).json()
    discoverer = {**agents[0], "model_override": "my-model:7b", "temperature": 0.9}
    await client.put(f"/api/ai-mode/agents/{discoverer['id']}", json=discoverer)

    await client.put("/api/ai-mode/settings", json={"enabled": True})  # only the on/off switch

    after = (await client.get("/api/ai-mode/agents")).json()[0]
    assert after["model_override"] == "my-model:7b" and after["temperature"] == 0.9

    await client.put("/api/ai-mode/settings", json={"temperature": 0.4})  # an explicit change still mirrors
    assert (await client.get("/api/ai-mode/agents")).json()[0]["temperature"] == 0.4


@pytest.mark.asyncio
async def test_start_and_stop_one_agent_over_the_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    agents = {a["name"]: a["id"] for a in (await client.get("/api/ai-mode/agents")).json()}
    reviewer, discoverer = agents["reviewer"], agents["discoverer"]
    assert (await client.post(f"/api/ai-mode/agents/{reviewer}/stop")).status_code == 409  # nothing running
    assert (await client.post(f"/api/ai-mode/agents/{reviewer}/start")).status_code == 409  # AI Mode is off

    await client.put("/api/ai-mode/settings", json={"enabled": True})
    network = (await client.post("/api/networks", json={"name": "lan", "cidr": "10.0.0.0/24"})).json()
    device = {
        "display_name": "box", "device_type": "other", "primary_ip": "10.0.0.5", "network_id": network["id"],
    }
    await client.post("/api/devices", json=device)

    async def slow(**kwargs: object) -> dict:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", slow)

    async def states() -> dict[str, str]:
        status = (await client.get("/api/ai-mode/status")).json()
        return {a["name"]: a["state"] for a in status["agents"]}

    async def until(expected: dict[str, str]) -> None:
        expected = {**{n: "waiting" for n in ("bellaco", "sinverguenza", "tajonaso")}, **expected}
        for _ in range(150):
            if await states() == expected:
                return
            await asyncio.sleep(0.02)
        assert await states() == expected

    # Idle: Start on the reviewer begins a run with the reviewer first; the discoverer just waits.
    started = await client.post(f"/api/ai-mode/agents/{reviewer}/start")
    assert started.status_code == 202
    await until({"discoverer": "waiting", "reviewer": "working", "reporter": "waiting"})
    assert (await client.post(f"/api/ai-mode/agents/{reviewer}/start")).status_code == 409  # already running

    # Give the discoverer work too, so the run stays alive while the reviewer is stopped.
    task = {"run_id": started.json()["run_id"], "topic": "task.discoverer", "text": "look at 10.0.0.5"}
    assert (await client.post("/api/ai-mode/messages", json=task)).status_code == 201
    await until({"discoverer": "working", "reviewer": "working", "reporter": "waiting"})

    assert (await client.post(f"/api/ai-mode/agents/{reviewer}/stop")).status_code == 202
    await until({"discoverer": "working", "reviewer": "stopped", "reporter": "waiting"})
    assert (await client.post(f"/api/ai-mode/agents/{reviewer}/stop")).status_code == 409  # already stopped

    assert (await client.post(f"/api/ai-mode/agents/{reviewer}/start")).status_code == 202  # rejoins this run
    await until({"discoverer": "working", "reviewer": "waiting", "reporter": "waiting"})

    run_id = started.json()["run_id"]
    assert (await client.post(f"/api/ai-mode/runs/{run_id}/stop")).status_code == 202
    assert discoverer  # the other agent was never touched


@pytest.mark.asyncio
async def test_starting_one_agent_can_pass_an_explicit_target_it_never_discovered(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A target doesn't need to already be a known Device - matching the AI Run page, which only
    validates a target against the configured network/loopback when a tool actually runs against it."""
    import asyncio

    await client.put("/api/ai-mode/settings", json={"enabled": True})
    await client.post("/api/networks", json={"name": "lan", "cidr": "10.0.0.0/24"})
    agents = {a["name"]: a["id"] for a in (await client.get("/api/ai-mode/agents")).json()}
    reviewer = agents["reviewer"]

    async def slow(**kwargs: object) -> dict:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", slow)

    # Idle: the explicit target/message become the run's entry task for an undiscovered host.
    started = await client.post(
        f"/api/ai-mode/agents/{reviewer}/start",
        json={"targets": ["10.0.0.99"], "message": "Look closely at this one host."},
    )
    assert started.status_code == 202
    run_id = started.json()["run_id"]

    async def until_working(name: str) -> None:
        for _ in range(150):
            status = (await client.get("/api/ai-mode/status")).json()
            if next(a["state"] for a in status["agents"] if a["name"] == name) == "working":
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"{name} never started working")

    await until_working("reviewer")
    task_message = next(
        m
        for m in (await client.get(f"/api/ai-mode/messages?run_id={run_id}")).json()
        if m["topic"] == "task.reviewer"
    )
    assert task_message["payload"]["text"] == "Look closely at this one host."
    assert task_message["payload"]["targets"] == ["10.0.0.99"]

    # Give the discoverer work too, so the run stays alive once the reviewer is stopped - otherwise
    # it would be the only agent with anything in flight, and stopping it would end the run outright.
    task = {"run_id": run_id, "topic": "task.discoverer", "text": "look at 10.0.0.5"}
    assert (await client.post("/api/ai-mode/messages", json=task)).status_code == 201

    # Mid-run: stop it, then restart it with a different explicit target - published straight to it.
    assert (await client.post(f"/api/ai-mode/agents/{reviewer}/stop")).status_code == 202
    resumed = await client.post(
        f"/api/ai-mode/agents/{reviewer}/start", json={"targets": ["10.0.0.77"]}
    )
    assert resumed.status_code == 202
    assert resumed.json()["run_id"] == run_id
    await until_working("reviewer")
    second_task = next(
        m
        for m in reversed((await client.get(f"/api/ai-mode/messages?run_id={run_id}")).json())
        if m["topic"] == "task.reviewer"
    )
    assert second_task["payload"]["targets"] == ["10.0.0.77"]
    assert second_task["payload"]["text"] == "Investigate: 10.0.0.77"

    assert (await client.post(f"/api/ai-mode/runs/{run_id}/stop")).status_code == 202


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        ["/bin/sh", "-c", "id"],
        ["sh", "-c", "id {target}"],
        ["python3", "-c", "import os"],
        ["/usr/bin/nmap", "{target}"],
        ["./nmap", "{target}"],
        ["nmap", "--script", "vuln", "{target}"],
        ["nmap", "-oN", "/tmp/out", "{target}"],
        ["nmap", "-iL", "/etc/passwd"],
        ["nc", "-e", "/bin/sh", "{target}", "{port}"],
        ["dig", "-f", "/etc/passwd"],
        ["whatweb", "--custom-plugin", "x.rb", "{target}"],
        ["nmap", "{target}{evil}"],
    ],
)
async def test_command_tools_cannot_run_arbitrary_programs(client: AsyncClient, command: list[str]) -> None:
    tool = {**COMMAND_TOOL, "name": "sneaky", "command": command}
    assert (await client.post("/api/ai-mode/custom-tools", json=tool)).status_code == 422


@pytest.mark.asyncio
async def test_allowed_command_tools_are_accepted(client: AsyncClient) -> None:
    commands = (["nmap", "-sV", "-p", "{port}", "{target}"], ["nc", "-n", "-w", "3", "{target}", "{port}"])
    for command in commands:
        tool = {**COMMAND_TOOL, "name": f"ok_{command[0]}", "command": command}
        assert (await client.post("/api/ai-mode/custom-tools", json=tool)).status_code == 201


@pytest.mark.asyncio
async def test_a_stored_tool_that_predates_the_policy_is_refused_at_run_time() -> None:
    from app.db.session import get_databases

    command = ["sh", "-c", "id"]
    tool = AiCustomTool(name="old", description="x", kind="command", command=command, parameters={})
    with pytest.raises(AgentToolError, match="not allowed"):
        await custom_tools.run_custom_tool(get_databases(), tool, [], {"target": "127.0.0.1"})
