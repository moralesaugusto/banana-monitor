import functools
import json

import httpx
import pytest
from httpx import AsyncClient

from app.llm import custom_tools, tool_availability

DOWN = "http://down.local/mcp"


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Only nmap is installed; one MCP server offers `scan`, another is unreachable."""
    monkeypatch.setattr(
        tool_availability.shutil, "which", lambda exe: "/usr/bin/nmap" if exe == "nmap" else None
    )
    calls: dict[str, list[str]] = {"tools/list": [], "tools/call": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DOWN:
            raise httpx.ConnectError("refused")
        body = json.loads(request.content)
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        calls.setdefault(body["method"], []).append(str(request.url))
        result = {"tools": [{"name": "scan"}]} if body["method"] == "tools/list" else {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        custom_tools.httpx, "AsyncClient", functools.partial(real, transport=httpx.MockTransport(handler))
    )
    return calls


async def _add(client: AsyncClient, **fields: object) -> None:
    body = {"description": "d", "kind": "mcp", "mcp_tool": "scan", **fields}
    assert (await client.post("/api/ai-mode/custom-tools", json=body)).status_code == 201


async def _availability(client: AsyncClient) -> dict[str, dict]:
    response = await client.get("/api/ai-mode/tools/availability")
    assert response.status_code == 200, response.text
    return {t["name"]: t for t in response.json()}


async def test_builtin_tools_report_their_binary(client: AsyncClient) -> None:
    tools = await _availability(client)
    assert tools["run_nmap"]["status"] == "ok"
    assert tools["discover_hosts"]["status"] == "ok"
    assert tools["run_nc"]["status"] == "missing" and "nc is not on PATH" in tools["run_nc"]["detail"]
    assert tools["remember"]["status"] == "ok"


async def test_custom_tools_are_checked_by_binary_and_by_what_the_mcp_server_offers(
    client: AsyncClient,
) -> None:
    await _add(client, name="web_probe", kind="command", command=["whatweb", "{target}"], mcp_tool=None)
    await _add(client, name="mcp_ok", mcp_url="http://up.local/mcp")
    await _add(client, name="mcp_gone", mcp_url="http://up.local/mcp", mcp_tool="removed")
    await _add(client, name="mcp_down", mcp_url=DOWN)

    tools = await _availability(client)

    assert tools["web_probe"]["status"] == "missing" and "whatweb" in tools["web_probe"]["detail"]
    assert tools["mcp_ok"]["status"] == "ok"
    assert tools["mcp_gone"]["status"] == "missing" and "removed" in tools["mcp_gone"]["detail"]
    assert tools["mcp_down"]["status"] == "unreachable"
    assert "ConnectError" in tools["mcp_down"]["detail"]


async def test_each_mcp_server_is_asked_once_and_never_called(
    client: AsyncClient, environment: dict[str, list[str]]
) -> None:
    for name in ("mcp_one", "mcp_two", "mcp_three"):
        await _add(client, name=name, mcp_url="http://up.local/mcp")
    await _availability(client)
    await _availability(client)  # within the cache window

    assert environment["tools/list"].count("http://up.local/mcp") == 1
    assert len(environment["tools/list"]) == len(set(environment["tools/list"]))
    assert environment["tools/call"] == []


async def test_web_tools_are_blocked_by_the_internet_kill_switch(client: AsyncClient) -> None:
    await client.put("/api/system/internet-access", json={"blocked": True})
    tools = await _availability(client)
    assert tools["fetch_url"]["status"] == "blocked"
    assert tools["run_nmap"]["status"] == "ok"


async def test_verify_warns_when_an_enabled_tool_cannot_run(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def models(host: str, timeout: float = 5.0) -> list[str]:
        return ["m"]

    async def reply(**kwargs: object) -> dict:
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("app.llm.agent_verify.list_models", models)
    monkeypatch.setattr("app.llm.agent_verify.call_chat_completions", reply)
    agent = {
        "name": "scout",
        "role": "r",
        "system_prompt": "p",
        "base_url": "",
        "model_override": "m",
        "temperature": 0.2,
        "max_iterations": 10,
        "enabled_tools": ["run_nc", "run_nmap"],
        "subscribes": [],
        "publishes": [],
        "require_approval": "none",
        "enabled": True,
        "allow_changes": False,
    }
    response = await client.post("/api/ai-mode/agents/verify", json=agent)
    checks = {c["id"]: c for c in response.json()["checks"]}
    assert checks["availability"]["status"] == "warn"
    assert "run_nc" in checks["availability"]["detail"] and "run_nmap" not in checks["availability"]["detail"]
