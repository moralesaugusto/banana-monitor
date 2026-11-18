"""Actually calls a custom tool (MCP or local command) to see whether it really works, not just
whether it is listed (that is `tool_availability.py`'s job). This executes for real - against the
test target below, through the exact same path (`run_custom_tool`) a real agent call takes, so it is
bound by the same target restriction (loopback or a configured network) and the same guardrails.

Required arguments the tool's own schema asks for but that have no safe generic value (anything
other than a target) are filled with an empty/zero placeholder - a tool that genuinely needs a real
value there will reject it, and that rejection is itself the problem being reported.
"""

import asyncio
import time
from typing import Any

from app.api.schemas.ai_mode import ToolTestResult
from app.db.session import Databases
from app.domain.models import AiCustomTool, AiGuardrail
from app.llm.custom_tools import _TARGET_KEYS, run_custom_tool
from app.llm.tool_base import AgentToolError

TEST_TARGET = "127.0.0.1"
"""Loopback: always allowed regardless of configured networks, and the one address guaranteed not to
belong to someone else's host - see app.llm.agent_tools._validate_target."""

TOOL_TEST_TIMEOUT_SECONDS = 15.0
TEST_ALL_CONCURRENCY = 10
"""Bounds total wall time for "test every tool" against a server backing many tools (HexStrike's ~150)."""


def synthesize_test_arguments(tool: AiCustomTool) -> dict[str, Any]:
    """A plausible, safe call for this tool's own schema: every required field gets a value, the
    target-shaped ones get TEST_TARGET, everything else gets its type's emptiest value."""
    if tool.kind == "command":
        return {"target": TEST_TARGET}
    schema = tool.parameters or {}
    properties: dict[str, Any] = schema.get("properties") or {}
    arguments: dict[str, Any] = {}
    for key in schema.get("required") or []:
        if key in _TARGET_KEYS:
            arguments[key] = TEST_TARGET
            continue
        json_type = str((properties.get(key) or {}).get("type") or "")
        arguments[key] = {"integer": 0, "number": 0, "boolean": False, "array": []}.get(json_type, "")
    return arguments


async def test_custom_tool(
    databases: Databases, tool: AiCustomTool, guardrails: list[AiGuardrail]
) -> ToolTestResult:
    arguments = synthesize_test_arguments(tool)
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            run_custom_tool(databases, tool, guardrails, dict(arguments)), TOOL_TEST_TIMEOUT_SECONDS
        )
        ok, detail = True, "Called successfully."
    except AgentToolError as exc:
        ok, detail = False, str(exc)
    except TimeoutError:
        ok, detail = False, f"Timed out after {TOOL_TEST_TIMEOUT_SECONDS:.0f}s."
    return ToolTestResult(
        id=tool.id,
        name=tool.name,
        ok=ok,
        detail=detail,
        duration_ms=int((time.monotonic() - started) * 1000),
        arguments_used=arguments,
    )


async def test_all_custom_tools(
    databases: Databases, tools: list[AiCustomTool], guardrails: list[AiGuardrail]
) -> list[ToolTestResult]:
    semaphore = asyncio.Semaphore(TEST_ALL_CONCURRENCY)

    async def bounded(tool: AiCustomTool) -> ToolTestResult:
        async with semaphore:
            return await test_custom_tool(databases, tool, guardrails)

    return list(await asyncio.gather(*(bounded(t) for t in tools)))
