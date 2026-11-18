"""Tool surface for the AI Mode discovery agent: local `nmap` and `nc`, plus
one write tool that records findings as unmanaged Services.

Safety model: no shell (argv lists only), targets must be a single IP inside
a configured Network CIDR (or loopback, so the agent can be exercised
locally), nmap flags come from a fixed allowlist (no scripts, no file
input/output), output is truncated, and every call has a hard timeout. The
model never supplies a raw command line.
"""

import asyncio
import contextlib
import ipaddress
import re
import socket
import ssl
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from ddgs import DDGS
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Databases
from app.discovery.network_scanner import MAX_HOSTS_PER_SCAN, host_count, scan_cidr
from app.discovery.service import DiscoveredServiceStore, DiscoveryService
from app.domain.bootstrap import ensure_default_ai_mode_settings, ensure_default_discovery_settings
from app.domain.enums import ServiceType
from app.domain.models import (
    FINDING_KINDS,
    FINDING_SEVERITIES,
    AiAgent,
    AiAgentMemory,
    Device,
    DeviceAddress,
    HostFinding,
    Network,
    Report,
    utcnow,
)
from app.knowledge import service as knowledge_service
from app.llm.inspect_tools import HANDLERS as _INSPECT_HANDLERS
from app.llm.inspect_tools import INSPECT_TOOL_NAMES, MUTATING_TOOLS
from app.llm.inspect_tools import SCHEMAS as _INSPECT_SCHEMAS
from app.llm.tool_base import AgentToolError, truncate
from app.llm.virustotal_tool import SCHEMA as VT_SCHEMA
from app.llm.virustotal_tool import virustotal_lookup
from app.reports.builder import build_snapshot, compute_delta
from app.telegram.bot import notify_report_saved

NMAP_TIMEOUT_SECONDS = 40.0
"""Hard limit per scan. Everything scanned is on the LAN, where a live host answers in milliseconds, so
a scan still running after this long is looking at a host that filters or drops packets."""
NMAP_LAN_DEFAULTS = {
    "-T": "-T4",
    "--host-timeout": "--host-timeout=30s",
    "--max-retries": "--max-retries=1",
    "--max-rtt-timeout": "--max-rtt-timeout=500ms",
}
"""Aggressive timing, added unless the model chose its own value: give up on a silent host within
30 s (before the hard limit, so nmap still prints what it found) instead of waiting out retries."""
NC_TIMEOUT_SECONDS = 8.0
FORM_SUBMIT_TIMEOUT_SECONDS = 15.0
DISCOVER_TIMEOUT_SECONDS = 120.0
"""A sweep over up to MAX_HOSTS_PER_SCAN hosts at network_scanner.SCAN_CONCURRENCY needs more
headroom than a single nmap call against one host."""
_truncate = truncate
WEB_TIMEOUT_SECONDS = 15.0
MAX_FETCH_BYTES = 1_000_000
MAX_REDIRECTS = 3


async def effective_memory_limits(session: AsyncSession, agent_name: str) -> tuple[int, int, int]:
    """Effective (max_entries, max_content_chars, max_inject_chars) for this agent: its own
    override if set (non-zero) for each, else the administrator's global default. The single
    place that resolves override-or-default for every `remember`/memory-injection size setting -
    `remember()` below uses the first two (write path); orchestrator._memory_context uses the
    third (injection path)."""
    settings = await ensure_default_ai_mode_settings(session)
    agent = await session.scalar(select(AiAgent).where(AiAgent.name == agent_name))
    max_entries = (agent and agent.memory_max_entries_override) or settings.memory_max_entries_per_agent
    max_chars = (agent and agent.memory_max_content_chars_override) or settings.memory_max_content_chars
    max_inject = (agent and agent.memory_max_inject_chars_override) or settings.memory_max_inject_chars
    return max_entries, max_chars, max_inject


_ALLOWED_FLAG = re.compile(
    r"^(-sT|-sV|-sn|-Pn|-n|-F|-T[0-5]|--open|--reason"
    r"|--version-intensity=[0-9]"
    r"|--host-timeout=\d{1,3}s"
    r"|--max-retries=\d"
    r"|--top-ports=\d{1,4})$"
)
_PORTS = re.compile(r"^[0-9,\-]{1,100}$")


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_nmap",
            "description": (
                "Run local nmap against ONE IP address on the monitored LAN. "
                "Allowed flags: -sT -sV -sn -Pn -n -F -T0..-T5 --open --reason "
                "--version-intensity=N --host-timeout=Ns --max-retries=N --top-ports=N."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "A single IPv4 address"},
                    "ports": {"type": "string", "description": "e.g. 22,80,443 or 1-1024 (optional)"},
                    "flags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_nc",
            "description": (
                "Connect with netcat to host:port, optionally send a short text payload, and "
                "return what the service sends back (banner grabbing). Set tls for an HTTPS or other "
                "TLS port (443, 8443, ...) - a plain connection to a TLS port returns nothing, since no "
                "handshake is performed; this is the signal to retry with tls instead of repeating the "
                "same plain attempt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "port": {"type": "integer"},
                    "payload": {"type": "string", "description": "optional text to send, max 256 chars"},
                    "tls": {
                        "type": "boolean",
                        "description": "complete a TLS handshake first (for HTTPS/TLS ports)",
                    },
                },
                "required": ["target", "port"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_service",
            "description": (
                "Record an open service you have identified. It appears in the Services tab. "
                "service_type is http, https, dns or tcp."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string"},
                    "port": {"type": "integer"},
                    "service_type": {"type": "string", "enum": ["http", "https", "dns", "tcp"]},
                    "name": {"type": "string", "description": "protocol/service name, e.g. ssh, postgresql"},
                    "product": {"type": "string"},
                    "version": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["ip", "port", "service_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_open_ports",
            "description": (
                "Report which ports are open on a host you already scanned, without identifying what is "
                "running on them - use this after a fast scan (no -sV), not after you have already "
                "identified the services. Another agent picks this up and does the slower, deeper "
                "identification. Do not call record_service yourself for these ports."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string"},
                    "ports": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "open ports found",
                    },
                },
                "required": ["ip", "ports"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_finding",
            "description": (
                "Record one thing you learned about a host so it appears in the run's report: its operating "
                "system and version (kind os), its patch level or pending updates (patch), a vulnerability "
                "or misconfiguration (vulnerability), a performance or capacity problem (performance) or a "
                "security incident (incident). Call it once per fact, as you learn it, not only at the end. "
                "Only record what you actually observed on the host; if something does not apply or you "
                "could not check it, say nothing rather than guess. Recording the same title again for the "
                "same host updates it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string"},
                    "kind": {"type": "string", "enum": list(FINDING_KINDS)},
                    "severity": {
                        "type": "string",
                        "enum": list(FINDING_SEVERITIES),
                        "description": "info for plain facts such as the OS version",
                    },
                    "title": {"type": "string", "description": "short, such as 'Debian 12.5'"},
                    "detail": {"type": "string", "description": "evidence and what to do, a sentence or two"},
                },
                "required": ["ip", "kind", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discover_hosts",
            "description": (
                "Ping- and port-sweep a whole CIDR to find hosts you don't already know about, recording "
                "any that answer (same place scanning the Networks page does: Devices/Services). Always "
                "inside a configured Network, any size up to that network's scan limit. Outside a "
                "configured Network only if the administrator has turned that on, and only for a private "
                "(RFC1918) range: 10.0.0.0/8, 172.16.0.0/12 or 192.168.0.0/16. Use this to find new "
                "devices, not run_nmap/run_nc, which only ever look at one address you already have."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cidr": {"type": "string", "description": "e.g. 10.0.0.0/24"},
                },
                "required": ["cidr"],
            },
        },
    },
]


TOOL_SCHEMAS.append(
    {
        "type": "function",
        "function": {
            "name": "publish_message",
            "description": (
                "Publish a message to a topic on the message bus. Every agent subscribed to a matching "
                "topic receives it, e.g. topic 'task.reviewer' with content telling the reviewer what to do. "
                "You may only publish to the topics your configuration allows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "dot-separated, e.g. task.reviewer"},
                    "content": {"type": "string"},
                },
                "required": ["topic", "content"],
            },
        },
    }
)

_Net = ipaddress.IPv4Network | ipaddress.IPv6Network


async def _allowed_networks(databases: Databases) -> list[tuple[int, _Net]]:
    async with databases.app_session_factory() as session:
        rows = (await session.execute(select(Network.id, Network.cidr))).all()
    networks = []
    for network_id, cidr in rows:
        try:
            networks.append((network_id, ipaddress.ip_network(cidr, strict=False)))
        except ValueError:
            continue
    return networks


async def _validate_target(databases: Databases, target: str) -> tuple[str, int | None, bool]:
    """Returns (normalized ip, containing network id or None, whether it's inside the configured
    discovery scope). Loopback is always in scope (so the agent can be exercised locally). A
    private (RFC1918) address outside every configured Network is also allowed - but only when the
    administrator's allow_undefined_network_scan switch is on, the same policy _validate_scan_cidr
    already applies to CIDR sweeps. A publicly routable address needs that same switch PLUS the
    further, explicitly-disclaimed allow_public_targets switch - this is attack surface on someone
    else's network, not the admin's own, so it is opt-in on top of the private-range relaxation, not
    instead of it. Either relaxation is reported out of scope so callers can flag it rather than
    silently treating it as a known device. Deliberately not offered for discover_hosts's CIDR
    sweeps - a public range is a mass-scanning capability this is not meant to grant."""
    try:
        ip = ipaddress.ip_address(target.strip())
    except ValueError as exc:
        raise AgentToolError(f"target must be a single IP address, got {target!r}") from exc
    if ip.is_loopback:
        return str(ip), None, True
    for network_id, net in await _allowed_networks(databases):
        if ip in net:
            return str(ip), network_id, True
    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
    if settings.allow_undefined_network_scan:
        if _is_rfc1918(ip):
            return str(ip), None, False
        if settings.allow_public_targets and ip.is_global:
            return str(ip), None, False
    raise AgentToolError(f"{ip} is not inside any configured network")


_RFC1918 = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def _is_rfc1918(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return isinstance(ip, ipaddress.IPv4Address) and any(ip in block for block in _RFC1918)


def _is_subnet_of(net: _Net, other: _Net) -> bool:
    if isinstance(net, ipaddress.IPv4Network) and isinstance(other, ipaddress.IPv4Network):
        return net.subnet_of(other)
    if isinstance(net, ipaddress.IPv6Network) and isinstance(other, ipaddress.IPv6Network):
        return net.subnet_of(other)
    return False


def _scope_note(ip: str, in_scope: bool) -> dict[str, Any]:
    if in_scope:
        return {}
    if ipaddress.ip_address(ip).is_global:
        return {
            "note": (
                f"{ip} is a PUBLIC address outside the configured network discovery scope - the "
                "administrator has explicitly enabled testing public targets. This is attack surface "
                "on a network that may not be yours; make sure you have authorization, and call this "
                "out prominently in your report."
            )
        }
    return {
        "note": (
            f"{ip} is outside the configured network discovery scope (not inside any configured "
            "Network) - proceeding anyway since undefined-range scanning is enabled; call this out "
            "in your report."
        )
    }


async def _validate_scan_cidr(databases: Databases, cidr: str) -> tuple[_Net, int | None, int]:
    """Returns (parsed network, containing registered network id or None, host-count limit to scan
    it with). A CIDR inside a configured Network is always allowed, up to that scan's usual limit; one
    that isn't needs the administrator's `allow_undefined_network_scan` switch on and must sit entirely
    inside RFC1918 private space, capped at the (smaller, since it was never vetted) configured limit."""
    try:
        net = ipaddress.ip_network(str(cidr).strip(), strict=False)
    except ValueError as exc:
        raise AgentToolError(f"cidr must be a valid network, got {cidr!r}") from exc
    for network_id, allowed in await _allowed_networks(databases):
        if _is_subnet_of(net, allowed):
            if host_count(net) > MAX_HOSTS_PER_SCAN:
                raise AgentToolError(f"{cidr} has more than the {MAX_HOSTS_PER_SCAN}-host scan limit")
            return net, network_id, MAX_HOSTS_PER_SCAN
    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
    if not settings.allow_undefined_network_scan:
        raise AgentToolError(
            f"{cidr} is not inside any configured network, and scanning outside configured "
            "networks is turned off (AI Mode > Settings > Discovery)"
        )
    if not any(_is_subnet_of(net, block) for block in _RFC1918):
        raise AgentToolError(
            f"{cidr} is not inside any configured network and is not a private (RFC1918) range"
        )
    if host_count(net) > settings.undefined_scan_max_hosts:
        raise AgentToolError(
            f"{cidr} has more hosts than the configured {settings.undefined_scan_max_hosts}-host "
            "limit for ranges outside configured networks"
        )
    return net, None, settings.undefined_scan_max_hosts


async def discover_hosts(databases: Databases, arguments: dict[str, Any]) -> Any:
    cidr = str(arguments.get("cidr", "")).strip()
    net, network_id, max_hosts = await _validate_scan_cidr(databases, cidr)
    try:
        return await asyncio.wait_for(
            scan_cidr(databases, str(net), network_id=network_id, max_hosts=max_hosts),
            DISCOVER_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise AgentToolError(f"scanning {cidr} timed out after {DISCOVER_TIMEOUT_SECONDS:.0f}s") from exc


async def _run(args: list[str], timeout: float, stdin: bytes | None = None) -> dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise AgentToolError(f"{args[0]} is not installed") from exc
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "exit_code": None,
            "output": (
                f"timed out after {timeout:.0f}s; scan fewer ports (for example --top-ports=20). "
                "A host that stays silent is probably filtering."
            ),
        }
    except asyncio.CancelledError:
        proc.kill()  # the agent was stopped: do not leave the command running
        raise
    return {"exit_code": proc.returncode, "output": _truncate(out.decode(errors="replace"))}


def _as_flag_list(value: Any) -> list[str]:
    """flags is documented as an array, but a model that writes its own flags as a plain
    space-separated string (the way the tool's own description shows them) must not silently have
    each character treated as its own "flag" - str is iterable too."""
    if isinstance(value, str):
        return value.split()
    if isinstance(value, list):
        return [str(f) for f in value]
    return []


def nmap_argv(ip: str, arguments: dict[str, Any]) -> list[str]:
    """The exact command run_nmap executes for these arguments; raises AgentToolError for a flag or port
    list the allowlist refuses. Split out so the Tools page can show a call's command without running it."""
    flags = _as_flag_list(arguments.get("flags"))
    for flag in flags:
        if not _ALLOWED_FLAG.match(flag):
            raise AgentToolError(f"flag not allowed: {flag!r}")
    for prefix, default in NMAP_LAN_DEFAULTS.items():
        if not any(flag.startswith(prefix) for flag in flags):
            flags.append(default)
    args = ["nmap", *flags]
    ports = arguments.get("ports")
    if ports:
        if not _PORTS.match(str(ports)):
            raise AgentToolError("ports must look like 22,80 or 1-1024")
        args += ["-p", str(ports)]
    return [*args, ip]


async def run_nmap(databases: Databases, arguments: dict[str, Any]) -> Any:
    ip, _, in_scope = await _validate_target(databases, str(arguments.get("target", "")))
    argv = nmap_argv(ip, arguments)
    result = await _run(argv, NMAP_TIMEOUT_SECONDS)
    if "due to host timeout" in str(result.get("output")):
        result["output"] += (
            "\nNOTE: nmap gave up on this host, so this says nothing about which ports are open. "
            "Retry it once with a short port list (for example ports=22,80,443) before reporting it."
        )
    result.update(_scope_note(ip, in_scope))
    return result


def nc_port(arguments: dict[str, Any]) -> int:
    """The port run_nc would dial. port is the documented key; ports (run_nmap's plural) is accepted too - a
    model that just used run_nmap naturally reaches for the same key name on this sibling tool, and nc only
    ever dials one port, so a comma-separated value takes its first entry."""
    raw_port = arguments.get("port", arguments.get("ports"))
    try:
        port = int(str(raw_port).split(",")[0].strip())
    except (TypeError, ValueError) as exc:
        raise AgentToolError("port (or ports) must be an integer, e.g. 22") from exc
    if not 1 <= port <= 65535:
        raise AgentToolError("port out of range")
    return port


async def run_nc(databases: Databases, arguments: dict[str, Any]) -> Any:
    ip, _, in_scope = await _validate_target(databases, str(arguments.get("target", "")))
    port = nc_port(arguments)
    payload = arguments.get("payload")
    stdin = str(payload)[:256].encode() if payload else b""
    if arguments.get("tls"):
        result = await _run_nc_tls(ip, port, stdin)
    else:
        result = await _run(["nc", "-n", "-w", "3", ip, str(port)], NC_TIMEOUT_SECONDS, stdin=stdin)
    result.update(_scope_note(ip, in_scope))
    return result


async def _run_nc_tls(ip: str, port: int, stdin: bytes) -> dict[str, Any]:
    """TLS equivalent of `_run(["nc", ...])`: a plain nc connection to a TLS port returns nothing (no
    handshake happens), which otherwise leaves the caller no way to actually read a TLS service's
    banner. No certificate validation, same reasoning as discovery's own tls_probe.py - many home
    services self-sign."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port, ssl=ctx), timeout=NC_TIMEOUT_SECONDS
        )
    except (OSError, TimeoutError, ssl.SSLError) as exc:
        return {"exit_code": 1, "output": f"tls connect failed: {type(exc).__name__}: {exc}"}
    try:
        if stdin:
            writer.write(stdin)
            await writer.drain()
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=NC_TIMEOUT_SECONDS)
        except TimeoutError:
            data = b""
        return {"exit_code": 0, "output": _truncate(data.decode(errors="replace"))}
    except (OSError, ssl.SSLError) as exc:
        # A peer that resets the connection after the handshake (a TLS-only port probed with a plain
        # HTTP request, say) is a tool result for the model to read, not a reason to abort the agent.
        return {"exit_code": 1, "output": f"tls connection failed: {type(exc).__name__}: {exc}"}
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


async def record_service(databases: Databases, arguments: dict[str, Any]) -> Any:
    ip, network_id, in_scope = await _validate_target(databases, str(arguments.get("ip", "")))
    try:
        port = int(arguments["port"])
        service_type = ServiceType(str(arguments["service_type"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentToolError("port (integer) and service_type (http|https|dns|tcp) are required") from exc
    if service_type not in (ServiceType.HTTP, ServiceType.HTTPS, ServiceType.DNS, ServiceType.TCP):
        raise AgentToolError("service_type must be http, https, dns or tcp")

    async with databases.app_session_factory() as session:
        device_id = (
            (await session.execute(select(DeviceAddress.device_id).where(DeviceAddress.ip_address == ip)))
            .scalars()
            .first()
        )
    if device_id is None:
        device_id = await DiscoveryService(databases).record_device_observation(
            network_id=network_id, ip=ip, mac=None, hostname=None, open_ports=[port], via="ai_mode"
        )

    fingerprint = {
        key: str(arguments[key]) for key in ("name", "product", "version", "notes") if arguments.get(key)
    }
    fingerprint["source"] = "ai"
    service_id = await DiscoveredServiceStore(databases).upsert(
        device_id=device_id,
        ip=ip,
        port=port,
        service_type=service_type.value,
        source="ai",
        fingerprint=fingerprint,
    )
    return {"recorded": True, "service_id": service_id, **_scope_note(ip, in_scope)}


async def report_open_ports(databases: Databases, arguments: dict[str, Any]) -> Any:
    ip, _, in_scope = await _validate_target(databases, str(arguments.get("ip", "")))
    try:
        ports = [int(p) for p in arguments["ports"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentToolError("ports (a list of integers) is required") from exc
    return {"reported": True, "ip": ip, "ports": ports, **_scope_note(ip, in_scope)}


async def record_finding(
    databases: Databases,
    arguments: dict[str, Any],
    *,
    agent_name: str | None = None,
    run_id: int | None = None,
) -> Any:
    ip, _, in_scope = await _validate_target(databases, str(arguments.get("ip", "")))
    kind = str(arguments.get("kind") or "").lower()
    severity = str(arguments.get("severity") or "info").lower()
    title = str(arguments.get("title") or "").strip()[:200]
    if kind not in FINDING_KINDS:
        raise AgentToolError(f"kind must be one of: {', '.join(FINDING_KINDS)}")
    if severity not in FINDING_SEVERITIES:
        raise AgentToolError(f"severity must be one of: {', '.join(FINDING_SEVERITIES)}")
    if not title:
        raise AgentToolError("title is required")
    detail = str(arguments.get("detail") or "").strip()[:2000]
    async with databases.app_session_factory() as session:
        device_id = await session.scalar(select(Device.id).where(Device.primary_ip == ip).limit(1))
        existing = await session.scalar(
            select(HostFinding).where(
                HostFinding.ip == ip,
                HostFinding.kind == kind,
                HostFinding.title == title,
                HostFinding.run_id.is_(None) if run_id is None else HostFinding.run_id == run_id,
            )
        )
        if existing is None:
            session.add(
                HostFinding(
                    run_id=run_id, device_id=device_id, ip=ip, kind=kind, severity=severity,
                    title=title, detail=detail, source=agent_name or "",
                )
            )
        else:
            existing.severity, existing.detail, existing.observed_at = severity, detail, utcnow()
        await session.commit()
    return {"recorded": True, "ip": ip, "kind": kind, **_scope_note(ip, in_scope)}


async def publish_message(databases: Databases, arguments: dict[str, Any]) -> Any:
    raise AgentToolError("publish_message is handled by the orchestrator")


TOOL_SCHEMAS.extend(
    [
        {
            "type": "function",
            "function": {
                "name": "get_network_snapshot",
                "description": (
                    "Read the current state of the network: networks, devices with their services "
                    "(port, product, version, status), counts by status and active alerts. Read-only. "
                    "Pass hosts (a list of IP addresses) to scope the result to just those devices - do "
                    "this whenever you already know which host(s) a message is about, instead of pulling "
                    "the whole inventory. Omit hosts only when you genuinely need the whole network."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hosts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "IP addresses to scope the snapshot to (optional).",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_status_delta",
                "description": (
                    "Read the current network snapshot together with what changed since the last "
                    "saved report: devices or services added or removed, status changes, and alerts "
                    "that are newly firing or resolved. Use this instead of get_network_snapshot when "
                    "writing a report, so it shows deltas rather than just a flat current state. Pass "
                    "hosts to scope both the current state and the delta to just those devices."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hosts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "IP addresses to scope to (optional).",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_report",
                "description": (
                    "Save a finished report. It appears on the Reports page, can be downloaded as PDF and "
                    "is sent to Telegram. content is Markdown (headings, bullets, pipe tables). Do not sign "
                    "or attribute the report yourself (no 'Generated by ...' line, whether to yourself or "
                    "to a tool you used) - the platform already records and displays which agent wrote it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["title", "content"],
                },
            },
        },
    ]
)


MAX_SNAPSHOT_DEVICES = 50
"""Backstop for an unscoped call on an install with a large inventory: an oversized snapshot in the
prompt is the single biggest contributor to a model call running long enough to hit the LLM timeout."""


async def get_network_snapshot(databases: Databases, arguments: dict[str, Any]) -> Any:
    snapshot = await build_snapshot(databases)
    hosts = arguments.get("hosts")
    if hosts:
        wanted = {str(h) for h in hosts}
        snapshot["devices"] = [d for d in snapshot["devices"] if d["ip"] in wanted]
        snapshot["unassigned_services"] = []  # not attributable to any of the requested hosts
        return snapshot
    total = len(snapshot["devices"])
    if total > MAX_SNAPSHOT_DEVICES:
        snapshot["devices"] = snapshot["devices"][:MAX_SNAPSHOT_DEVICES]
        snapshot["devices_truncated"] = True
        snapshot["device_count_total"] = total
    return snapshot


async def get_status_delta(databases: Databases, arguments: dict[str, Any]) -> Any:
    current = await build_snapshot(databases)
    hosts = arguments.get("hosts")
    wanted = {str(h) for h in hosts} if hosts else None
    if wanted:
        current["devices"] = [d for d in current["devices"] if d["ip"] in wanted]
    async with databases.app_session_factory() as session:
        previous_report = await session.scalar(
            select(Report)
            .where(Report.snapshot.is_not(None), Report.scope.is_(None))
            .order_by(Report.id.desc())
            .limit(1)
        )
    if previous_report is None or previous_report.snapshot is None:
        return {"current": current, "previous": None, "delta": None}
    previous = previous_report.snapshot
    previous_devices = previous.get("devices", [])
    if wanted:
        previous_devices = [d for d in previous_devices if d.get("ip") in wanted]
    delta = compute_delta({**previous, "devices": previous_devices}, current)
    return {
        "current": current,
        "previous": {
            "report_id": previous_report.id,
            "title": previous_report.title,
            "generated_at": previous.get("generated_at"),
        },
        "delta": delta,
    }


_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s*")


async def save_report(
    databases: Databases, arguments: dict[str, Any], *, agent_name: str | None = None
) -> Any:
    # A model sometimes passes its own markdown heading as the plain-text title; strip it rather than
    # show "## Investigation Report: ..." literally on the Reports list.
    title = _MARKDOWN_HEADING.sub("", str(arguments.get("title") or "").strip()).strip()
    content = str(arguments.get("content") or "").strip()
    if not title or not content:
        raise AgentToolError("title and content are required")
    source = f"agent:{agent_name}" if agent_name else "agent"
    snapshot = await build_snapshot(databases)
    async with databases.app_session_factory() as session:
        report = Report(title=title[:200], content=content, source=source, snapshot=snapshot)
        session.add(report)
        await session.commit()
        report_id = report.id
    notify_report_saved(databases, report_id)
    return {"saved": True, "report_id": report_id}


async def remember(databases: Databases, arguments: dict[str, Any], *, agent_name: str | None = None) -> Any:
    """Save a short note for this agent's own future runs. Pruned to the most recent entries per
    the effective cap (AiModeSettings default, or this agent's own override); visible and
    deletable by the human on the Agents page."""
    note = str(arguments.get("note") or "").strip()
    if not note:
        raise AgentToolError("note is required")
    if not agent_name:
        raise AgentToolError("remember has no agent to save this for")
    async with databases.app_session_factory() as session:
        max_entries, max_chars, _ = await effective_memory_limits(session, agent_name)
        content = note[:max_chars]
        session.add(AiAgentMemory(agent_name=agent_name, content=content))
        await session.flush()
        stale = (
            (
                await session.execute(
                    select(AiAgentMemory.id)
                    .where(AiAgentMemory.agent_name == agent_name)
                    .order_by(AiAgentMemory.created_at.desc(), AiAgentMemory.id.desc())
                    .offset(max_entries)
                )
            )
            .scalars()
            .all()
        )
        if stale:
            await session.execute(delete(AiAgentMemory).where(AiAgentMemory.id.in_(stale)))
        await session.commit()
    return {"saved": True, "note": content}


async def search_knowledge(databases: Databases, arguments: dict[str, Any]) -> Any:
    collection = str(arguments.get("collection") or "").strip()
    query = str(arguments.get("query") or "").strip()
    if not collection or not query:
        raise AgentToolError("collection and query are required")
    try:
        top_k = max(1, min(int(arguments.get("top_k") or 5), 20))
    except (TypeError, ValueError) as exc:
        raise AgentToolError("top_k must be a whole number") from exc
    return await knowledge_service.search(databases, collection_name=collection, query=query, top_k=top_k)


async def add_knowledge_entry(
    databases: Databases, arguments: dict[str, Any], *, agent_name: str | None = None
) -> Any:
    collection = str(arguments.get("collection") or "").strip()
    title = str(arguments.get("title") or "").strip()
    content = str(arguments.get("content") or "").strip()
    if not collection or not title or not content:
        raise AgentToolError("collection, title and content are required")
    source = f"agent:{agent_name}" if agent_name else "agent"
    entries = await knowledge_service.add_entry(
        databases,
        collection_name=collection,
        title=title,
        content=content,
        source=source,
        create_collection_if_missing=False,
    )
    return {"saved": True, "entry_ids": [e.id for e in entries]}


TOOL_SCHEMAS.extend(_INSPECT_SCHEMAS)
TOOL_SCHEMAS.append(VT_SCHEMA)

TOOL_SCHEMAS.extend(
    [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the internet (DuckDuckGo). Returns up to 10 results.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "description": "1-10, default 5"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": (
                    "Download a public http(s) web page and return its text. Addresses on the local "
                    "network, loopback and link-local are refused."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_http_form",
                "description": (
                    "Make an HTTP request to a host on the monitored LAN - a curl equivalent. GET, POST, "
                    "PUT, PATCH, DELETE or HEAD; a GET's fields become its query string, a POST/PUT/PATCH's "
                    "fields become a form-encoded body. For a raw body (e.g. JSON) use body instead of "
                    "fields and set Content-Type via headers - fields and body are mutually exclusive. Only "
                    "targets inside a configured Network or loopback are allowed, same as run_nmap/run_nc. "
                    "Certificates are not validated (home services often self-sign)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "A single IPv4 or IPv6 address"},
                        "port": {"type": "integer"},
                        "path": {"type": "string", "description": "e.g. /login (default /)"},
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                        },
                        "fields": {
                            "type": "object",
                            "description": 'Form field name/value pairs, e.g. {"username": "admin"}',
                        },
                        "body": {
                            "type": "string",
                            "description": "Raw request body (e.g. JSON text), instead of fields",
                        },
                        "headers": {"type": "object", "description": "Optional extra request headers"},
                        "tls": {"type": "boolean", "description": "Use https instead of http"},
                        "follow_redirects": {"type": "boolean"},
                    },
                    "required": ["target", "port", "method"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": (
                    "Save a short note for your own future runs, e.g. a fact worth not "
                    "re-discovering or re-flagging next time. Visible to you on every future run "
                    "and manageable (viewable, deletable) by the human on your Agents page."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {
                            "type": "string",
                            "description": "One short fact or finding, kept brief.",
                        }
                    },
                    "required": ["note"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_knowledge",
                "description": (
                    "Search a knowledge collection by meaning, not exact words. Returns the most "
                    "relevant entries with a similarity score, most relevant first. Refuses if the "
                    "knowledge base is turned off (Settings), or if the collection name doesn't exist."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "collection": {
                            "type": "string",
                            "description": "An existing collection's exact name",
                        },
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "description": "1-20, default 5"},
                    },
                    "required": ["collection", "query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_knowledge_entry",
                "description": (
                    "Save a finding into an existing knowledge collection, for anyone (including "
                    "yourself later) to find by search_knowledge. Never creates a new collection - "
                    "the collection must already exist, by its exact name."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "collection": {
                            "type": "string",
                            "description": "An existing collection's exact name",
                        },
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["collection", "title", "content"],
                },
            },
        },
    ]
)


async def web_search(databases: Databases, arguments: dict[str, Any]) -> Any:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise AgentToolError("query is required")
    count = max(1, min(int(arguments.get("max_results") or 5), 10))
    try:
        search = DDGS(timeout=int(WEB_TIMEOUT_SECONDS)).text
        results = await asyncio.to_thread(search, query, max_results=count)
    except Exception as exc:  # ddgs raises its own hierarchy (rate limit, no results, network)
        raise AgentToolError(f"search failed: {exc}") from exc
    return [{"title": r["title"], "url": r["href"], "snippet": r["body"]} for r in results]


async def _require_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise AgentToolError("only http(s) URLs are allowed")
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(parts.hostname, parts.port or 443)
    except socket.gaierror as exc:
        raise AgentToolError(f"cannot resolve {parts.hostname}") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise AgentToolError("refusing to fetch a non-public address")


async def fetch_url(databases: Databases, arguments: dict[str, Any]) -> Any:
    url = str(arguments.get("url") or "").strip()
    async with httpx.AsyncClient(timeout=WEB_TIMEOUT_SECONDS, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await _require_public_url(url)
            try:
                async with client.stream("GET", url, headers={"User-Agent": "banana-agent"}) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    body = b""
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) >= MAX_FETCH_BYTES:
                            break
                    text = body.decode(response.encoding or "utf-8", errors="replace")
                    return {"url": url, "status": response.status_code, "text": _truncate(text)}
            except httpx.HTTPError as exc:
                raise AgentToolError(f"fetch failed: {exc}") from exc
    raise AgentToolError("too many redirects")


_FORM_HIDDEN_HEADERS = {"set-cookie", "authorization", "proxy-authorization"}


_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")


async def submit_http_form(databases: Databases, arguments: dict[str, Any]) -> Any:
    ip, _, in_scope = await _validate_target(databases, str(arguments.get("target", "")))
    try:
        port = int(arguments["port"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentToolError("port must be an integer") from exc
    method = str(arguments.get("method", "")).upper()
    if method not in _HTTP_METHODS:
        raise AgentToolError(f"method must be one of {', '.join(_HTTP_METHODS)}")
    fields = arguments.get("fields")
    if fields is not None and not isinstance(fields, dict):
        raise AgentToolError("fields must be an object of field name/value pairs")
    body = arguments.get("body")
    if body is not None and not isinstance(body, str):
        raise AgentToolError("body must be a string")
    if fields and body is not None:
        raise AgentToolError(
            "fields and body are mutually exclusive - use fields for a form, body for raw content"
        )
    path = str(arguments.get("path") or "/")
    if not path.startswith("/"):
        path = "/" + path
    scheme = "https" if arguments.get("tls") else "http"
    host = f"[{ip}]" if ":" in ip else ip
    url = f"{scheme}://{host}:{port}{path}"
    raw_headers = arguments.get("headers") or {}
    if not isinstance(raw_headers, dict):
        raise AgentToolError("headers must be an object")
    headers = {k: str(v) for k, v in raw_headers.items() if isinstance(k, str)}
    follow = bool(arguments.get("follow_redirects"))
    params = fields if method == "GET" and fields else None
    data = fields if method != "GET" and fields else None

    try:
        async with httpx.AsyncClient(
            verify=False, timeout=FORM_SUBMIT_TIMEOUT_SECONDS, follow_redirects=follow
        ) as client:
            response = await client.request(
                method, url, params=params, data=data, content=body, headers=headers
            )
    except httpx.HTTPError as exc:
        raise AgentToolError(f"form submission failed: {type(exc).__name__}: {exc}") from exc

    return {
        "url": str(response.url),
        "status": response.status_code,
        "headers": {k: v for k, v in response.headers.items() if k.lower() not in _FORM_HIDDEN_HEADERS},
        "body": _truncate(response.text),
        **_scope_note(ip, in_scope),
    }


_HANDLERS = {
    "run_nmap": run_nmap,
    "run_nc": run_nc,
    "record_service": record_service,
    "report_open_ports": report_open_ports,
    "record_finding": record_finding,
    "discover_hosts": discover_hosts,
    "publish_message": publish_message,
    "get_network_snapshot": get_network_snapshot,
    "get_status_delta": get_status_delta,
    "save_report": save_report,
    "web_search": web_search,
    "fetch_url": fetch_url,
    "submit_http_form": submit_http_form,
    "remember": remember,
    "search_knowledge": search_knowledge,
    "add_knowledge_entry": add_knowledge_entry,
    **_INSPECT_HANDLERS,
    "virustotal_lookup": virustotal_lookup,
}


ALL_TOOL_NAMES = list(_HANDLERS)
WEB_TOOL_NAMES = frozenset({"web_search", "fetch_url", "virustotal_lookup"})
KNOWLEDGE_TOOL_NAMES = frozenset({"search_knowledge", "add_knowledge_entry"})


def schemas_for(enabled: list[str]) -> list[dict[str, Any]]:
    return [t for t in TOOL_SCHEMAS if t["function"]["name"] in enabled]


async def dispatch(
    databases: Databases,
    name: str,
    arguments: dict[str, Any],
    *,
    enabled: list[str] | None = None,
    dry_run: bool = False,
    agent_name: str | None = None,
    run_id: int | None = None,
) -> Any:
    handler = _HANDLERS.get(name)
    if handler is None or (enabled is not None and name not in enabled):
        raise AgentToolError(f"unknown or disabled tool {name!r}")
    if name in WEB_TOOL_NAMES:
        async with databases.app_session_factory() as session:
            if (await ensure_default_discovery_settings(session)).agent_internet_blocked:
                raise AgentToolError("internet access is blocked by the administrator's kill switch")
    if name in KNOWLEDGE_TOOL_NAMES:
        async with databases.app_session_factory() as session:
            if not (await ensure_default_ai_mode_settings(session)).knowledge_base_enabled:
                raise AgentToolError("the knowledge base is turned off (AI Settings)")
    if dry_run and name == "record_service":
        return {"recorded": False, "dry_run": True, "would_record": arguments}
    if dry_run and name == "report_open_ports":
        return {"reported": False, "dry_run": True, "would_report": arguments}
    if dry_run and name == "record_finding":
        return {"recorded": False, "dry_run": True, "would_record": arguments}
    if dry_run and name == "discover_hosts":
        return {"scanned": False, "dry_run": True, "would_scan": arguments.get("cidr")}
    if dry_run and name in MUTATING_TOOLS:
        return {"changed": False, "dry_run": True, "would_run": name, "arguments": arguments}
    if dry_run and name == "save_report":
        return {"saved": False, "dry_run": True}
    if dry_run and name == "submit_http_form":
        return {"submitted": False, "dry_run": True, "would_submit": arguments}
    if dry_run and name == "remember":
        return {"saved": False, "dry_run": True, "note": str(arguments.get("note") or "")}
    if dry_run and name == "add_knowledge_entry":
        return {"saved": False, "dry_run": True}
    if name == "remember":
        return await remember(databases, arguments, agent_name=agent_name)
    if name == "record_finding":
        return await record_finding(databases, arguments, agent_name=agent_name, run_id=run_id)
    if name == "save_report":
        return await save_report(databases, arguments, agent_name=agent_name)
    if name == "add_knowledge_entry":
        return await add_knowledge_entry(databases, arguments, agent_name=agent_name)
    if name in INSPECT_TOOL_NAMES:
        return await _INSPECT_HANDLERS[name](databases, arguments, agent_name=agent_name)
    return await handler(databases, arguments)
