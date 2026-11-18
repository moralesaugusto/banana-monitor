import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.domain.models import AiAgent


@pytest.fixture(autouse=True)
def nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("trying a call must never run a program")

    monkeypatch.setattr("app.llm.agent_tools._run", refuse)
    monkeypatch.setattr("app.llm.custom_tools._run", refuse)


async def _agent(client: AsyncClient, name: str = "discoverer") -> dict:
    return next(a for a in (await client.get("/api/ai-mode/agents")).json() if a["name"] == name)


async def _try(client: AsyncClient, tool: str, arguments: dict, agent: dict | None = None) -> dict:
    body = {"arguments": arguments, "agent_id": agent["id"] if agent else None}
    response = await client.post(f"/api/ai-mode/tools/{tool}/try", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    data["by_id"] = {s["id"]: s for s in data["stages"]}
    return data


def _statuses(trace: dict) -> dict[str, str]:
    return {s["id"]: s["status"] for s in trace["stages"]}


async def test_an_allowed_nmap_call_shows_the_exact_command_and_runs_nothing(client: AsyncClient) -> None:
    trace = await _try(
        client, "run_nmap", {"target": "127.0.0.1", "flags": "-Pn -sT", "ports": "80"}, await _agent(client)
    )

    assert trace["would_run"] is True
    assert trace["command"].startswith("nmap -Pn -sT") and trace["command"].endswith("-p 80 127.0.0.1")
    assert _statuses(trace)["enabled"] == "pass" and _statuses(trace)["result"] == "pass"
    assert "Nothing was run" in trace["by_id"]["result"]["detail"]


async def test_a_refused_flag_stops_at_the_tools_own_checks_and_later_steps_are_not_reached(
    client: AsyncClient,
) -> None:
    trace = await _try(
        client, "run_nmap", {"target": "127.0.0.1", "flags": ["--script=vuln"]}, await _agent(client)
    )

    assert trace["would_run"] is False
    assert _statuses(trace)["checks"] == "stop"
    assert "flag not allowed" in trace["by_id"]["checks"]["detail"]
    assert _statuses(trace)["result"] == "skip" and "Not reached" in trace["by_id"]["result"]["detail"]


async def test_a_target_outside_every_network_is_stopped(client: AsyncClient) -> None:
    trace = await _try(client, "run_nc", {"target": "8.8.8.8", "port": 53})
    assert "not inside any configured network" in trace["by_id"]["checks"]["detail"]
    assert _statuses(trace)["enabled"] == "skip"  # no agent was chosen


async def test_a_tool_the_agent_does_not_hold_stops_early(client: AsyncClient) -> None:
    agent = await _agent(client)
    body = {k: v for k, v in agent.items() if k not in ("id", "created_at", "updated_at")}
    await client.put(
        f"/api/ai-mode/agents/{agent['id']}", json={**body, "enabled_tools": ["publish_message"]}
    )

    trace = await _try(client, "run_nmap", {"target": "127.0.0.1"}, agent)

    assert _statuses(trace)["enabled"] == "stop" and "never offered" in trace["by_id"]["enabled"]["detail"]
    assert _statuses(trace)["guardrails"] == "skip"


async def test_guardrail_scope_decides_whether_a_built_in_tool_is_covered(client: AsyncClient) -> None:
    rule = {"name": "no-loopback", "kind": "deny_regex", "pattern": "127\\."}
    created = (await client.post("/api/ai-mode/guardrails", json=rule)).json()
    args = {"target": "127.0.0.1"}

    default = await _try(client, "run_nmap", args)
    assert (
        _statuses(default)["guardrails"] == "skip"
        and "none cover this tool" in default["by_id"]["guardrails"]["detail"]
    )
    assert default["would_run"] is True

    await client.put(f"/api/ai-mode/guardrails/{created['id']}", json={**rule, "applies_to": "all"})
    widened = await _try(client, "run_nmap", args)
    assert _statuses(widened)["guardrails"] == "stop"
    assert "blocked by guardrail 'no-loopback'" in widened["by_id"]["guardrails"]["detail"]

    ssh = await _try(client, "ssh_readonly", {"integration_id": 1, "command": "ip addr 127.0.0.1"})
    assert _statuses(ssh)["guardrails"] == "stop"  # inspection tools were always covered


async def test_a_host_changing_tool_needs_permission_and_always_asks_a_human(client: AsyncClient) -> None:
    agent = await _agent(client)
    body = {k: v for k, v in agent.items() if k not in ("id", "created_at", "updated_at")}
    await client.put(
        f"/api/ai-mode/agents/{agent['id']}",
        json={**body, "enabled_tools": ["apply_updates"], "allow_changes": True},
    )
    allowed = await _try(client, "apply_updates", {"integration_id": 1}, agent)
    assert _statuses(allowed)["changes"] == "pass" and _statuses(allowed)["approval"] == "note"
    assert allowed["would_run"] is True

    # The API will not save this combination, but a row edited by hand can have it; the gate must still hold.
    async with get_databases().app_session_factory() as session:
        (await session.get(AiAgent, agent["id"])).allow_changes = False  # type: ignore[union-attr]
        await session.commit()
    refused = await _try(client, "apply_updates", {"integration_id": 1}, agent)
    assert _statuses(refused)["changes"] == "stop" and refused["would_run"] is False


async def test_the_kill_switch_and_url_rules_stop_internet_tools(client: AsyncClient) -> None:
    assert _statuses(await _try(client, "fetch_url", {"url": "http://10.0.0.1/"}))["checks"] == "stop"
    ok = await _try(client, "fetch_url", {"url": "https://1.1.1.1/"})
    assert ok["would_run"] is True

    await client.put("/api/system/internet-access", json={"blocked": True})
    blocked = await _try(client, "fetch_url", {"url": "https://1.1.1.1/"})
    assert _statuses(blocked)["kill_switch"] == "stop"


async def test_unknown_tools_and_agents(client: AsyncClient) -> None:
    unknown = await _try(client, "no_such_tool", {})
    assert _statuses(unknown)["exists"] == "stop" and unknown["would_run"] is False

    response = await client.post("/api/ai-mode/tools/run_nmap/try", json={"arguments": {}, "agent_id": 9999})
    assert response.status_code == 404


async def test_custom_tools_are_walked_through_the_same_gates(client: AsyncClient) -> None:
    tool = {"name": "web_probe", "description": "d", "kind": "command", "command": ["whatweb", "{target}"]}
    assert (await client.post("/api/ai-mode/custom-tools", json=tool)).status_code == 201

    trace = await _try(client, "web_probe", {"target": "127.0.0.1"})

    assert trace["would_run"] is True and trace["command"] == "whatweb 127.0.0.1"
