from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.llm.custom_tools import McpListing
from app.llm.tool_base import AgentToolError

URL = "http://hex.local:8891/mcp"
BASE = "/api/ai-mode/mcp-servers"


def _listing(*tools: dict) -> McpListing:
    return McpListing("hexstrike", "6.0", list(tools))


NMAP = {
    "name": "nmap-scan",
    "description": "Port scan",
    "inputSchema": {"type": "object", "properties": {"target": {}}},
}
EXEC = {
    "name": "execute_command",
    "description": "Run it",
    "inputSchema": {"type": "object", "properties": {"command": {}}},
}


async def _add_server(client: AsyncClient) -> int:
    created = await client.post(BASE, json={"name": "HexStrike", "url": URL})
    assert created.status_code == 201
    return int(created.json()["id"])


@pytest.mark.asyncio
async def test_test_connection_reports_the_server_and_saves_nothing(client: AsyncClient) -> None:
    with patch("app.api.routes.ai_mcp.list_mcp_tools", AsyncMock(return_value=_listing(NMAP, EXEC))):
        result = (await client.post(f"{BASE}/test", json={"url": URL})).json()
    assert result["ok"] is True
    assert (result["server_name"], result["tool_count"]) == ("hexstrike", 2)
    assert result["tool_names"] == ["nmap-scan", "execute_command"]
    assert (await client.get(BASE)).json() == []


@pytest.mark.asyncio
async def test_test_connection_failure_is_reported_not_raised(client: AsyncClient) -> None:
    failing = AsyncMock(side_effect=AgentToolError("MCP server did not answer (ConnectError)"))
    with patch("app.api.routes.ai_mcp.list_mcp_tools", failing):
        result = (await client.post(f"{BASE}/test", json={"url": URL})).json()
    assert result["ok"] is False
    assert "did not answer" in result["detail"]


@pytest.mark.asyncio
async def test_import_creates_valid_tools_flags_unscoped_ones_and_is_idempotent(client: AsyncClient) -> None:
    server_id = await _add_server(client)
    with patch("app.api.routes.ai_mcp.list_mcp_tools", AsyncMock(return_value=_listing(NMAP, EXEC))):
        first = (await client.post(f"{BASE}/{server_id}/import", json={})).json()
        again = (await client.post(f"{BASE}/{server_id}/import", json={})).json()

    assert (first["added"], first["updated"]) == (2, 0)
    assert first["unscoped"] == ["execute_command"]
    assert (again["added"], again["updated"]) == (0, 0)
    tools = {t["name"]: t for t in (await client.get("/api/ai-mode/custom-tools")).json()}
    assert tools["nmap_scan"]["mcp_tool"] == "nmap-scan"  # a name the server wrote with a dash is made valid
    assert tools["nmap_scan"]["mcp_url"] == URL
    assert (await client.get(BASE)).json()[0]["tool_count"] == 2


@pytest.mark.asyncio
async def test_import_prefixes_a_name_that_is_already_taken_and_refreshes_changes(
    client: AsyncClient,
) -> None:
    server_id = await _add_server(client)
    builtin_clash = {"name": "run_nmap", "description": "x"}
    with patch("app.api.routes.ai_mcp.list_mcp_tools", AsyncMock(return_value=_listing(builtin_clash, NMAP))):
        await client.post(f"{BASE}/{server_id}/import", json={})
    names = {t["name"] for t in (await client.get("/api/ai-mode/custom-tools")).json()}
    assert "hexstrike_run_nmap" in names

    changed = {**NMAP, "description": "New text"}
    with patch(
        "app.api.routes.ai_mcp.list_mcp_tools", AsyncMock(return_value=_listing(builtin_clash, changed))
    ):
        result = (await client.post(f"{BASE}/{server_id}/import", json={"remove_missing": False})).json()
    assert result["updated"] == 1
    tools = {t["name"]: t for t in (await client.get("/api/ai-mode/custom-tools")).json()}
    assert tools["nmap_scan"]["description"] == "New text"


@pytest.mark.asyncio
async def test_import_can_remove_tools_the_server_dropped(client: AsyncClient) -> None:
    server_id = await _add_server(client)
    with patch("app.api.routes.ai_mcp.list_mcp_tools", AsyncMock(return_value=_listing(NMAP, EXEC))):
        await client.post(f"{BASE}/{server_id}/import", json={})
    with patch("app.api.routes.ai_mcp.list_mcp_tools", AsyncMock(return_value=_listing(NMAP))):
        kept = (await client.post(f"{BASE}/{server_id}/import", json={})).json()
        removed = (await client.post(f"{BASE}/{server_id}/import", json={"remove_missing": True})).json()
    assert kept["removed"] == 0
    assert removed["removed"] == 1
    assert (await client.get(BASE)).json()[0]["tool_count"] == 1


@pytest.mark.asyncio
async def test_unreachable_server_import_is_a_502_and_changes_nothing(client: AsyncClient) -> None:
    server_id = await _add_server(client)
    failing = AsyncMock(side_effect=AgentToolError("MCP server did not answer (ConnectError)"))
    with patch("app.api.routes.ai_mcp.list_mcp_tools", failing):
        response = await client.post(f"{BASE}/{server_id}/import", json={})
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_editing_the_url_repoints_its_tools(client: AsyncClient) -> None:
    server_id = await _add_server(client)
    with patch("app.api.routes.ai_mcp.list_mcp_tools", AsyncMock(return_value=_listing(NMAP))):
        await client.post(f"{BASE}/{server_id}/import", json={})
    moved = "http://new-host:9000/mcp"
    await client.put(f"{BASE}/{server_id}", json={"name": "HexStrike", "url": moved})
    tool = next(t for t in (await client.get("/api/ai-mode/custom-tools")).json() if t["name"] == "nmap_scan")
    assert tool["mcp_url"] == moved


@pytest.mark.asyncio
async def test_duplicate_server_name_is_rejected(client: AsyncClient) -> None:
    await _add_server(client)
    assert (await client.post(BASE, json={"name": "HexStrike", "url": URL})).status_code == 409


@pytest.mark.asyncio
async def test_delete_removes_the_server_its_tools_and_every_reference_to_them(client: AsyncClient) -> None:
    server_id = await _add_server(client)
    with patch("app.api.routes.ai_mcp.list_mcp_tools", AsyncMock(return_value=_listing(NMAP, EXEC))):
        await client.post(f"{BASE}/{server_id}/import", json={})
    other = {
        "name": "whatweb_scan",
        "description": "d",
        "kind": "command",
        "command": ["whatweb", "{target}"],
    }
    await client.post("/api/ai-mode/custom-tools", json=other)
    await client.put("/api/ai-mode/settings", json={"enabled_tools": ["nmap_scan", "whatweb_scan"]})
    agents = (await client.get("/api/ai-mode/agents")).json()
    agent_id = agents[0]["id"]
    await client.put(
        f"/api/ai-mode/agents/{agent_id}",
        json={**agents[0], "enabled_tools": ["nmap_scan", "execute_command"]},
    )

    deleted = await client.delete(f"{BASE}/{server_id}")

    assert deleted.json() == {"tools_removed": 2}
    assert (await client.get(BASE)).json() == []
    names = {t["name"] for t in (await client.get("/api/ai-mode/custom-tools")).json()}
    assert "whatweb_scan" in names
    assert not names & {"nmap_scan", "execute_command"}
    assert (await client.get("/api/ai-mode/settings")).json()["enabled_tools"] == ["whatweb_scan"]
    agent = next(a for a in (await client.get("/api/ai-mode/agents")).json() if a["id"] == agent_id)
    assert not set(agent["enabled_tools"]) & {"nmap_scan", "execute_command"}
