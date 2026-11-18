"""Is each AI tool usable right now? Looks for the binary or asks the MCP server what it offers; never
runs a tool, so nothing here touches a target."""

import asyncio
import shutil
import time
from collections.abc import Collection
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.ai_mode import ToolAvailability
from app.domain.bootstrap import ensure_default_discovery_settings
from app.domain.models import AiCustomTool
from app.llm.agent_tools import ALL_TOOL_NAMES, WEB_TOOL_NAMES
from app.llm.custom_tools import list_mcp_tool_names
from app.llm.tool_base import AgentToolError

BUILTIN_BINARIES = {"run_nmap": "nmap", "run_nc": "nc", "discover_hosts": "nmap"}
MCP_CHECK_TIMEOUT_SECONDS = 5.0
MCP_CACHE_SECONDS = 30.0

# url -> (checked at, offered tool names or the error text). One server commonly backs ~150 tools, and the
# Tools page and every agent Verify would otherwise each open a session to it.
_mcp_cache: dict[str, tuple[float, set[str] | str]] = {}


async def _mcp_offer(url: str) -> set[str] | str:
    cached = _mcp_cache.get(url)
    if cached and time.monotonic() - cached[0] < MCP_CACHE_SECONDS:
        return cached[1]
    try:
        offer: set[str] | str = await list_mcp_tool_names(url, MCP_CHECK_TIMEOUT_SECONDS)
    except AgentToolError as exc:
        offer = str(exc)
    _mcp_cache[url] = (time.monotonic(), offer)
    return offer


def _binary(name: str, kind: str, executable: str) -> ToolAvailability:
    if shutil.which(executable):
        return ToolAvailability(name=name, kind=kind, status="ok", detail=f"{executable} found")  # type: ignore[arg-type]
    return ToolAvailability(name=name, kind=kind, status="missing", detail=f"{executable} is not on PATH")  # type: ignore[arg-type]


def _builtin(name: str, internet_blocked: bool) -> ToolAvailability:
    if name in BUILTIN_BINARIES:
        return _binary(name, "builtin", BUILTIN_BINARIES[name])
    if name in WEB_TOOL_NAMES and internet_blocked:
        detail = "Internet kill switch is on (System page)"
        return ToolAvailability(name=name, kind="builtin", status="blocked", detail=detail)
    return ToolAvailability(name=name, kind="builtin", status="ok", detail="Built in")


async def tool_availability(
    session: AsyncSession, names: Collection[str] | None = None
) -> list[ToolAvailability]:
    """Every built-in and custom tool, or only `names`."""
    wanted = None if names is None else set(names)
    internet_blocked = (await ensure_default_discovery_settings(session)).agent_internet_blocked
    results = [_builtin(n, internet_blocked) for n in ALL_TOOL_NAMES if wanted is None or n in wanted]

    customs = list(await session.scalars(select(AiCustomTool).order_by(AiCustomTool.name)))
    customs = [t for t in customs if wanted is None or t.name in wanted]
    urls = sorted({t.mcp_url for t in customs if t.kind == "mcp" and t.mcp_url})
    offers = dict(zip(urls, await asyncio.gather(*(_mcp_offer(u) for u in urls)), strict=True))
    for tool in customs:
        if tool.kind == "command":
            results.append(_binary(tool.name, "command", tool.command[0] if tool.command else ""))
            continue
        offer = offers.get(tool.mcp_url or "")
        where = urlsplit(tool.mcp_url or "").netloc or "no URL set"
        if offer is None:
            result = ("missing", "No MCP URL is set")
        elif isinstance(offer, str):
            result = ("unreachable", f"{where}: {offer}")
        elif tool.mcp_tool in offer:
            result = ("ok", f"{where} offers {tool.mcp_tool}")
        else:
            result = ("missing", f"{where} does not offer {tool.mcp_tool}")
        results.append(ToolAvailability(name=tool.name, kind="mcp", status=result[0], detail=result[1]))  # type: ignore[arg-type]
    return results
