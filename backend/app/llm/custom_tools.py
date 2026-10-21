"""Runs user-defined AI Mode tools (local command or MCP server) behind the same
target validation as the built-ins, plus the user's own guardrail regexes."""

import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.db.session import Databases
from app.domain.enums import EventSeverity
from app.domain.models import AiCustomTool, AiGuardrail, Event
from app.llm.agent_tools import NMAP_TIMEOUT_SECONDS, _run, _truncate, _validate_target
from app.llm.command_policy import validate_command
from app.llm.tool_base import AgentToolError

MCP_TIMEOUT_SECONDS = 30.0
_TARGET_KEYS = ("target", "ip", "host")
COMMAND_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "description": "A single IPv4 address"},
        "port": {"type": "integer", "description": "optional port"},
    },
    "required": ["target"],
}


def schema_for(tool: AiCustomTool) -> dict[str, Any]:
    parameters = COMMAND_PARAMETERS if tool.kind == "command" else tool.parameters
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description, "parameters": parameters},
    }


def check_guardrails(guardrails: list[AiGuardrail], values: list[str]) -> None:
    for rule in guardrails:
        if not rule.enabled:
            continue
        for value in values:
            matched = re.search(rule.pattern, value) is not None
            if (rule.kind == "deny_regex" and matched) or (rule.kind == "allow_regex" and not matched):
                raise AgentToolError(f"blocked by guardrail {rule.name!r}: {value!r}")


def string_values(arguments: dict[str, Any]) -> list[str]:
    return [str(v) for v in arguments.values() if v is not None and not isinstance(v, dict | list)]


async def run_custom_tool(
    databases: Databases,
    tool: AiCustomTool,
    guardrails: list[AiGuardrail],
    arguments: dict[str, Any],
    mcp_url_override: str | None = None,
    mcp_timeout_seconds: float = 0.0,
) -> Any:
    for key in _TARGET_KEYS:
        if key in arguments:
            arguments[key], _ = await _validate_target(databases, str(arguments[key]))
    check_guardrails(guardrails, string_values(arguments))

    if tool.kind == "command":
        if "target" not in arguments:
            raise AgentToolError("target is required")
        try:
            validate_command(tool.command)  # also checked when the tool is saved; stored rows predate that
        except ValueError as exc:
            raise AgentToolError(f"tool {tool.name!r} is not allowed to run: {exc}") from exc
        target, port = str(arguments["target"]), str(arguments.get("port", ""))
        argv = [part.replace("{target}", target).replace("{port}", port) for part in tool.command]
        check_guardrails(guardrails, argv[1:])
        return await _run(argv, NMAP_TIMEOUT_SECONDS)
    mcp_url = mcp_url_override or tool.mcp_url
    timeout = mcp_timeout_seconds or MCP_TIMEOUT_SECONDS
    await _audit_outbound(databases, tool, mcp_url)
    return await _call_mcp(tool, arguments, mcp_url, timeout)


async def _audit_outbound(databases: Databases, tool: AiCustomTool, mcp_url: str | None) -> None:
    """Every request an MCP tool makes leaves a trace of where it went."""
    destination = urlsplit(mcp_url or "")
    async with databases.app_session_factory() as session:
        session.add(
            Event(
                source="ai",
                severity=EventSeverity.INFO,
                category="outbound",
                message=f"MCP tool {tool.name} called {destination.scheme}://{destination.netloc}",
            )
        )
        await session.commit()


def _rpc_result(response: httpx.Response) -> dict[str, Any]:
    """MCP servers answer either plain JSON or a one-event SSE stream."""
    text = response.text
    if "text/event-stream" in response.headers.get("content-type", ""):
        data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = data_lines[-1] if data_lines else "{}"
    body = json.loads(text or "{}")
    if "error" in body:
        raise AgentToolError(f"MCP error: {body['error'].get('message', body['error'])}")
    result: dict[str, Any] = body.get("result", {})
    return result


async def _call_mcp(
    tool: AiCustomTool,
    arguments: dict[str, Any],
    mcp_url: str | None = None,
    timeout: float = MCP_TIMEOUT_SECONDS,
) -> Any:
    mcp_url = mcp_url or tool.mcp_url
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    assert mcp_url and tool.mcp_tool
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            init = await client.post(
                mcp_url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "banana", "version": "1"},
                    },
                },
            )
            _rpc_result(init)
            if session_id := init.headers.get("mcp-session-id"):
                headers["Mcp-Session-Id"] = session_id
            await client.post(
                mcp_url, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
            call = await client.post(
                mcp_url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool.mcp_tool, "arguments": arguments},
                },
            )
            result = _rpc_result(call)
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        # The exception text can carry the URL and network details; the audit event records the destination.
        raise AgentToolError(f"MCP call failed: {type(exc).__name__}") from exc
    text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    return {"is_error": bool(result.get("isError")), "output": _truncate(text)}
