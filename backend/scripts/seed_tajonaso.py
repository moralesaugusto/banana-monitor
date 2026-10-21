"""Force-refresh tool: re-applies every HexStrike AI tool definition (kind="mcp") and the "tajonaso"
agent's enabled_tools from scripts/hexstrike_tools.json, overwriting existing rows.

A brand-new install does NOT need this: domain/bootstrap.py creates tajonaso and its tools
automatically on first start, the same one-shot pattern as discoverer/reviewer/bellaco/sinverguenza
(see AiModeSettings.tajonaso_seeded). This script exists only to re-sync tool definitions on an
install that already has them - for example after HexStrike's own tool catalog changes upstream and
app/domain/hexstrike_tools.json is regenerated and re-committed - since bootstrap only ever runs once.

To point tajonaso at a different HexStrike VM, do NOT rerun this script: edit "MCP server override"
on the agent's edit page (or PUT /api/ai-mode/agents/{id} with mcp_url_override) - a one-field change,
not a reseed.

Run from backend/: uv run python scripts/seed_tajonaso.py
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.api.schemas.ai_mode import AgentBase, CustomToolBase
from app.db.session import get_databases
from app.domain.bootstrap import TAJONASO_PROMPT
from app.domain.models import AiAgent, AiCustomTool

HEXSTRIKE_MCP_URL = "http://192.168.1.10:8891/mcp"
TOOLS_FILE = Path(__file__).parent.parent / "app" / "domain" / "hexstrike_tools.json"


async def _upsert_custom_tool(session, spec: dict) -> None:
    payload = CustomToolBase(
        name=spec["name"],
        description=spec["description"],
        kind="mcp",
        mcp_url=HEXSTRIKE_MCP_URL,
        mcp_tool=spec["name"],
        parameters=spec["parameters"],
    )
    query = select(AiCustomTool).where(AiCustomTool.name == payload.name)
    existing = (await session.execute(query)).scalar_one_or_none()
    if existing is None:
        session.add(AiCustomTool(**payload.model_dump()))
    else:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)


async def _upsert_tajonaso(session, tool_names: list[str]) -> None:
    payload = AgentBase(
        name="tajonaso",
        display_name="Tajonaso",
        role="Offensive security testing against the LAN via HexStrike AI",
        system_prompt=TAJONASO_PROMPT,
        provider="ollama",
        model_override="gpt-oss:20b",
        enabled_tools=[*tool_names, "save_report"],
        mcp_url_override=HEXSTRIKE_MCP_URL,
        mcp_timeout_seconds=120.0,
        max_iterations=30,
        subscribes=[],
        publishes=[],
        require_approval="none",
    )
    query = select(AiAgent).where(AiAgent.name == payload.name)
    existing = (await session.execute(query)).scalar_one_or_none()
    if existing is None:
        session.add(AiAgent(**payload.model_dump()))
    else:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)


async def main() -> None:
    tools = json.loads(TOOLS_FILE.read_text())
    databases = get_databases()
    async with databases.app_session_factory() as session:
        for spec in tools:
            await _upsert_custom_tool(session, spec)
        await _upsert_tajonaso(session, [t["name"] for t in tools])
        await session.commit()
    print(f"Registered {len(tools)} HexStrike tools and the tajonaso agent.")


if __name__ == "__main__":
    asyncio.run(main())
