"""MCP servers: test one, import every tool it offers as custom tools, refresh, and delete it together
with its tools. The tools themselves are ordinary AiCustomTool rows (see llm/custom_tools.py)."""

import re
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import AppSession
from app.api.schemas.ai_mode import (
    McpDeleteResult,
    McpImportRequest,
    McpImportResult,
    McpServerBase,
    McpServerRead,
    McpTestRequest,
    McpTestResult,
)
from app.domain.bootstrap import ensure_default_ai_mode_settings
from app.domain.enums import EventSeverity
from app.domain.models import AiAgent, AiCustomTool, AiMcpServer, Event
from app.llm.agent_tools import ALL_TOOL_NAMES
from app.llm.custom_tools import _TARGET_KEYS, McpListing, list_mcp_tools
from app.llm.tool_base import AgentToolError

router = APIRouter(prefix="/ai-mode/mcp-servers", tags=["ai-mode"])

MCP_IMPORT_TIMEOUT_SECONDS = 20.0
_NAME_PREVIEW = 20


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")


def _tool_name(mcp_name: str, server: AiMcpServer, taken: set[str]) -> str:
    """A valid custom-tool name (lowercase, 3-40 chars) from whatever the server calls the tool; prefixed
    with the server's name only when the plain name is a built-in or already used."""
    base = _slug(mcp_name)
    if not base or not base[0].isalpha():
        base = f"tool_{base}"
    base = base.ljust(3, "_")[:40]
    if base not in taken:
        return base
    prefix = _slug(server.name) or "mcp"
    candidate = f"{prefix}_{base}"[:40]
    n = 2
    while candidate in taken:
        suffix = f"_{n}"
        candidate = f"{prefix}_{base}"[: 40 - len(suffix)] + suffix
        n += 1
    return candidate


async def _server_or_404(session: AppSession, server_id: int) -> AiMcpServer:
    server = await session.get(AiMcpServer, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


async def _audit(session: AppSession, action: str, url: str) -> None:
    destination = urlsplit(url)
    session.add(
        Event(
            source="ai",
            severity=EventSeverity.INFO,
            category="outbound",
            message=f"MCP server {action} called {destination.scheme}://{destination.netloc}",
        )
    )


async def _check_name(session: AppSession, name: str, own_id: int | None) -> None:
    taken = await session.scalar(select(AiMcpServer.id).where(AiMcpServer.name == name))
    if taken is not None and taken != own_id:
        raise HTTPException(status_code=409, detail=f"An MCP server named {name} already exists")


async def _read(session: AppSession, server: AiMcpServer) -> McpServerRead:
    count = await session.scalar(
        select(func.count()).select_from(AiCustomTool).where(AiCustomTool.mcp_server_id == server.id)
    )
    return McpServerRead(id=server.id, name=server.name, url=server.url, tool_count=count or 0)


@router.get("", response_model=list[McpServerRead])
async def list_servers(session: AppSession) -> list[McpServerRead]:
    servers = (await session.scalars(select(AiMcpServer).order_by(AiMcpServer.name))).all()
    return [await _read(session, s) for s in servers]


@router.post("", response_model=McpServerRead, status_code=201)
async def create_server(payload: McpServerBase, session: AppSession) -> McpServerRead:
    await _check_name(session, payload.name, None)
    server = AiMcpServer(**payload.model_dump())
    session.add(server)
    await session.commit()
    return await _read(session, server)


@router.put("/{server_id}", response_model=McpServerRead)
async def update_server(server_id: int, payload: McpServerBase, session: AppSession) -> McpServerRead:
    server = await _server_or_404(session, server_id)
    await _check_name(session, payload.name, server_id)
    server.name, server.url = payload.name, payload.url
    for tool in await session.scalars(select(AiCustomTool).where(AiCustomTool.mcp_server_id == server_id)):
        tool.mcp_url = payload.url
    await session.commit()
    return await _read(session, server)


@router.post("/test", response_model=McpTestResult)
async def test_connection(payload: McpTestRequest, session: AppSession) -> McpTestResult:
    """Handshake and list the tools; saves nothing and calls no tool."""
    await _audit(session, "test", payload.url)
    await session.commit()
    started = time.monotonic()
    try:
        listing = await list_mcp_tools(payload.url, MCP_IMPORT_TIMEOUT_SECONDS)
    except (AgentToolError, KeyError, TypeError, AttributeError) as exc:
        return McpTestResult(ok=False, detail=str(exc), duration_ms=int((time.monotonic() - started) * 1000))
    names = [str(t.get("name", "")) for t in listing.tools]
    return McpTestResult(
        ok=True,
        detail=f"Connected; the server offers {len(names)} tools.",
        server_name=listing.server_name,
        server_version=listing.server_version,
        tool_count=len(names),
        tool_names=names[:_NAME_PREVIEW],
        duration_ms=int((time.monotonic() - started) * 1000),
    )


async def _apply_listing(
    session: AppSession, server: AiMcpServer, listing: McpListing, remove_missing: bool
) -> McpImportResult:
    existing = {
        t.mcp_tool: t
        for t in await session.scalars(select(AiCustomTool).where(AiCustomTool.mcp_server_id == server.id))
    }
    taken = set(ALL_TOOL_NAMES) | set(await session.scalars(select(AiCustomTool.name)))
    added = updated = 0
    unscoped: list[str] = []
    offered: set[str] = set()
    for item in listing.tools:
        mcp_name = item.get("name")
        if not isinstance(mcp_name, str) or not mcp_name:
            continue
        offered.add(mcp_name)
        parameters = item.get("inputSchema") or {"type": "object", "properties": {}}
        description = (str(item.get("description") or "") or mcp_name)[:1000]
        tool = existing.get(mcp_name)
        if tool is None:
            tool = AiCustomTool(
                name=_tool_name(mcp_name, server, taken),
                kind="mcp",
                mcp_tool=mcp_name,
                mcp_server_id=server.id,
            )
            taken.add(tool.name)
            session.add(tool)
            added += 1
        elif (tool.description, tool.parameters, tool.mcp_url) != (description, parameters, server.url):
            updated += 1
        tool.description, tool.parameters, tool.mcp_url = description, parameters, server.url
        if not set(parameters.get("properties") or {}) & set(_TARGET_KEYS):
            unscoped.append(tool.name)
    removed = 0
    if remove_missing:
        gone = [t for name, t in existing.items() if name not in offered]
        removed = len(gone)
        await _remove_tools(session, gone)
    return McpImportResult(added=added, updated=updated, removed=removed, unscoped=unscoped)


async def _remove_tools(session: AppSession, tools: list[AiCustomTool]) -> None:
    """Deletes the tools and takes their names off the global and every agent's enabled list."""
    names = {t.name for t in tools}
    settings = await ensure_default_ai_mode_settings(session)
    settings.enabled_tools = [n for n in settings.enabled_tools if n not in names]
    for agent in await session.scalars(select(AiAgent)):
        if names & set(agent.enabled_tools):
            agent.enabled_tools = [n for n in agent.enabled_tools if n not in names]
    for tool in tools:
        await session.delete(tool)


@router.post("/{server_id}/import", response_model=McpImportResult)
async def import_tools(server_id: int, payload: McpImportRequest, session: AppSession) -> McpImportResult:
    """Adds the server's tools, and refreshes the description and schema of ones already imported. Never
    changes which agents may use a tool: a new tool is available to none until ticked on an agent."""
    server = await _server_or_404(session, server_id)
    await _audit(session, "import", server.url)
    try:
        listing = await list_mcp_tools(server.url, MCP_IMPORT_TIMEOUT_SECONDS)
    except AgentToolError as exc:
        await session.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result = await _apply_listing(session, server, listing, payload.remove_missing)
    await session.commit()
    return result


@router.delete("/{server_id}", response_model=McpDeleteResult)
async def delete_server(server_id: int, session: AppSession) -> McpDeleteResult:
    server = await _server_or_404(session, server_id)
    tools = list(await session.scalars(select(AiCustomTool).where(AiCustomTool.mcp_server_id == server_id)))
    await _remove_tools(session, tools)
    await session.delete(server)
    await session.commit()
    return McpDeleteResult(tools_removed=len(tools))
