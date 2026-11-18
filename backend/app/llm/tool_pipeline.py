"""Walks one tool call through the same gates a real call passes, without running anything.

The order mirrors `orchestrator._run_tool` and `agent_tools.dispatch`, and each check reuses the function the
real call uses, so what this reports is what would happen. It is for learning how a model's request is
stopped, not a second copy of the rules."""

import contextlib
import ipaddress
import shlex
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.ai_mode import PipelineStage, ToolTrace
from app.db.session import Databases
from app.discovery.network_scanner import host_count
from app.domain.bootstrap import ensure_default_discovery_settings
from app.domain.models import AiAgent, AiCustomTool, AiGuardrail, Integration
from app.llm.agent_tools import (
    ALL_TOOL_NAMES,
    WEB_TOOL_NAMES,
    _validate_scan_cidr,
    _validate_target,
    nc_port,
    nmap_argv,
)
from app.llm.command_policy import validate_command
from app.llm.custom_tools import _TARGET_KEYS, check_guardrails, string_values
from app.llm.guardrail_scope import guardrails_for
from app.llm.inspect_policy import PolicyError, check_linux, check_proxmox_path, check_windows
from app.llm.inspect_tools import MUTATING_TOOLS
from app.llm.tool_base import AgentToolError
from app.llm.tool_guide import TOOL_GUIDES

Gate = tuple[str, str]  # (status, detail)
NOT_REACHED = "Not reached: an earlier step stopped the call."


async def trace_call(
    session: AsyncSession,
    databases: Databases,
    name: str,
    arguments: dict[str, Any],
    agent: AiAgent | None,
) -> ToolTrace:
    custom = await session.scalar(select(AiCustomTool).where(AiCustomTool.name == name))
    rules = list(await session.scalars(select(AiGuardrail).where(AiGuardrail.enabled)))
    command: list[str] = []

    async def exists() -> Gate:
        if custom is not None or name in ALL_TOOL_NAMES:
            return "pass", "A custom tool." if custom else "A built-in tool."
        raise AgentToolError(f"There is no tool called {name!r}.")

    async def enabled() -> Gate:
        if agent is None:
            return "skip", "No agent chosen, so this was not checked."
        if name not in agent.enabled_tools:
            raise AgentToolError(
                f"{agent.name} does not have {name} enabled, so the model is never offered it."
            )
        return "pass", f"{agent.name} has it enabled."

    async def changes() -> Gate:
        if name not in MUTATING_TOOLS:
            return "skip", "Not a tool that changes hosts."
        if agent is None:
            return "skip", "This tool changes hosts; pick an agent to check its permission."
        if not agent.allow_changes:
            raise AgentToolError(f"{agent.name} may not change hosts, so {name} is refused.")
        return "pass", f"{agent.name} may change hosts."

    async def approval() -> Gate:
        if name in MUTATING_TOOLS:
            return "note", "A human is always asked before this tool runs; the run pauses until they answer."
        if agent is not None and agent.require_approval in ("tools", "both"):
            return "note", f"{agent.name} is set to ask a human before every tool call; the run pauses here."
        return "pass", "No human approval is needed."

    async def guardrails() -> Gate:
        applicable = guardrails_for(name, rules, custom_tool=custom is not None)
        if not rules:
            return "skip", "You have no guardrails defined."
        if not applicable:
            return "skip", (
                f"{len(rules)} guardrail(s) exist, but none cover this tool. A rule covers custom and "
                "host-inspection tools unless its scope is set to all tools."
            )
        check_guardrails(applicable, string_values(arguments))
        return "pass", f"{len(applicable)} guardrail(s) checked every argument value; none matched."

    async def kill_switch() -> Gate:
        if name not in WEB_TOOL_NAMES:
            return "skip", "Not an internet tool."
        if (await ensure_default_discovery_settings(session)).agent_internet_blocked:
            raise AgentToolError("Internet access is blocked by the administrator's kill switch.")
        return "pass", "The internet kill switch is off."

    async def checks() -> Gate:
        if custom is not None:
            return await _check_custom(databases, custom, arguments, command)
        return await _CHECKS.get(name, _no_checks)(session, databases, arguments, command)

    async def result() -> Gate:
        if command:
            return "pass", "Would run exactly: " + shlex.join(command) + ". Nothing was run."
        where = TOOL_GUIDES[name].where if name in TOOL_GUIDES else "A custom tool."
        return "pass", f"{where} Nothing was run."

    gates: list[tuple[str, str, Callable[[], Awaitable[Gate]]]] = [
        ("exists", "Is it a tool the model can be given?", exists),
        ("enabled", "Is it enabled for this agent?", enabled),
        ("changes", "Is the agent allowed to change hosts?", changes),
        ("approval", "Does a human have to approve it?", approval),
        ("guardrails", "Do your guardrails allow these arguments?", guardrails),
        ("kill_switch", "Is internet access allowed?", kill_switch),
        ("checks", "Do the tool's own checks accept the arguments?", checks),
        ("result", "What would happen?", result),
    ]
    stages: list[PipelineStage] = []
    stopped = False
    for stage_id, title, gate in gates:
        if stopped:
            stages.append(PipelineStage(id=stage_id, title=title, status="skip", detail=NOT_REACHED))
            continue
        try:
            status, detail = await gate()
        except AgentToolError as exc:
            stopped = True
            status, detail = "stop", str(exc)
        stages.append(PipelineStage(id=stage_id, title=title, status=status, detail=detail))  # type: ignore[arg-type]
    return ToolTrace(stages=stages, would_run=not stopped, command=" ".join(command) if command else None)


async def _no_checks(
    session: AsyncSession, databases: Databases, arguments: dict[str, Any], command: list[str]
) -> Gate:
    return "skip", "This tool has no argument checks beyond the fields it requires."


async def _target(arguments: dict[str, Any], key: str, databases: Databases) -> tuple[str, bool]:
    ip, _, in_scope = await _validate_target(databases, str(arguments.get(key, "")))
    return ip, in_scope


def _scope_phrase(ip: str, in_scope: bool) -> str:
    if in_scope:
        return f"{ip} is inside a configured network"
    return f"{ip} is outside every configured network, but allowed (undefined-range scanning is on)"


async def _check_nmap(
    session: AsyncSession, databases: Databases, arguments: dict[str, Any], command: list[str]
) -> Gate:
    ip, in_scope = await _target(arguments, "target", databases)
    command.extend(nmap_argv(ip, arguments))
    return "pass", f"{_scope_phrase(ip, in_scope)}, and every flag and the port list are allowed."


async def _check_nc(
    session: AsyncSession, databases: Databases, arguments: dict[str, Any], command: list[str]
) -> Gate:
    ip, in_scope = await _target(arguments, "target", databases)
    port = nc_port(arguments)
    if arguments.get("tls"):
        return (
            "pass",
            f"{ip}:{port} is allowed. Banana makes the TLS connection itself, so no program is run.",
        )
    command.extend(["nc", "-n", "-w", "3", ip, str(port)])
    return "pass", f"{_scope_phrase(ip, in_scope)} and {port} is a valid port."


async def _check_ip_field(
    session: AsyncSession, databases: Databases, arguments: dict[str, Any], command: list[str]
) -> Gate:
    key = "ip" if "ip" in arguments else "target"
    ip, in_scope = await _target(arguments, key, databases)
    return "pass", f"{_scope_phrase(ip, in_scope)}. Other fields are checked when the call runs."


async def _check_discover(
    session: AsyncSession, databases: Databases, arguments: dict[str, Any], command: list[str]
) -> Gate:
    net, _, limit = await _validate_scan_cidr(databases, str(arguments.get("cidr", "")))
    return "pass", f"{net} has {host_count(net)} hosts, within the limit of {limit}."


async def _check_fetch(
    session: AsyncSession, databases: Databases, arguments: dict[str, Any], command: list[str]
) -> Gate:
    parts = urlsplit(str(arguments.get("url") or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise AgentToolError("Only http and https URLs are allowed.")
    try:
        literal = ipaddress.ip_address(parts.hostname)
    except ValueError:
        return (
            "pass",
            "The host name is looked up when the call runs and refused if it points at a private address.",
        )
    if not literal.is_global:
        raise AgentToolError("Refusing to fetch a non-public address.")
    return "pass", f"{literal} is a public address."


async def _check_ssh(
    session: AsyncSession, databases: Databases, arguments: dict[str, Any], command: list[str]
) -> Gate:
    integration = None
    with contextlib.suppress(TypeError, ValueError):
        integration = await session.get(Integration, int(arguments.get("integration_id")))  # type: ignore[arg-type]
    family = (integration.config.get("os_family") if integration else None) or "linux"
    check = check_windows if family == "windows" else check_linux
    try:
        accepted = check(str(arguments.get("command") or ""))
    except PolicyError as exc:
        raise AgentToolError(str(exc)) from exc
    return (
        "pass",
        f"Allowed as a read-only {family} command: {accepted}. The integration is looked up when it runs.",
    )


async def _check_winrm(
    session: AsyncSession, databases: Databases, arguments: dict[str, Any], command: list[str]
) -> Gate:
    try:
        accepted = check_windows(str(arguments.get("command") or ""))
    except PolicyError as exc:
        raise AgentToolError(str(exc)) from exc
    return "pass", f"Allowed as a read-only PowerShell command: {accepted}."


async def _check_proxmox(
    session: AsyncSession, databases: Databases, arguments: dict[str, Any], command: list[str]
) -> Gate:
    try:
        path = check_proxmox_path(str(arguments.get("path") or ""))
    except PolicyError as exc:
        raise AgentToolError(str(exc)) from exc
    return "pass", f"{path} is an allowed read-only API path."


_CHECKS: dict[str, Callable[[AsyncSession, Databases, dict[str, Any], list[str]], Awaitable[Gate]]] = {
    "run_nmap": _check_nmap,
    "run_nc": _check_nc,
    "record_service": _check_ip_field,
    "report_open_ports": _check_ip_field,
    "record_finding": _check_ip_field,
    "submit_http_form": _check_ip_field,
    "discover_hosts": _check_discover,
    "fetch_url": _check_fetch,
    "ssh_readonly": _check_ssh,
    "winrm_readonly": _check_winrm,
    "proxmox_get": _check_proxmox,
}


async def _check_custom(
    databases: Databases, tool: AiCustomTool, arguments: dict[str, Any], command: list[str]
) -> Gate:
    for key in _TARGET_KEYS:
        if key in arguments:
            await _target(arguments, key, databases)
    if tool.kind == "mcp":
        server = urlsplit(tool.mcp_url or "").netloc
        return "pass", f"Would be sent as a call to the MCP tool {tool.mcp_tool} at {server}."
    if "target" not in arguments:
        raise AgentToolError("target is required")
    try:
        validate_command(tool.command)
    except ValueError as exc:
        raise AgentToolError(f"This tool is not allowed to run: {exc}") from exc
    target, port = str(arguments["target"]), str(arguments.get("port", ""))
    command.extend(part.replace("{target}", target).replace("{port}", port) for part in tool.command)
    return "pass", "The target is allowed and the command passes the command policy."
