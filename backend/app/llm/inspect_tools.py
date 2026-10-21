"""Agent tools that look inside hosts through the stored integrations.

The credential an integration holds is decrypted here, used, and dropped: it is a local variable and never
appears in a result, a trace or a log. What an agent may ask a host is decided by `inspect_policy` (read-only
programs and cmdlets only). `apply_updates` is the one tool that changes a host; see `MUTATING_TOOLS`."""

import asyncio
import contextlib
import datetime
import json
import ssl
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from cryptography import x509
from sqlalchemy import select

from app.credentials.crypto import MasterKeyError, get_secret_box
from app.credentials.service import CredentialNotFoundError, CredentialService
from app.db.session import Databases
from app.domain.enums import EventSeverity, ServiceType
from app.domain.models import Device, Event, Integration, Service
from app.integrations.generic_ssh.exec import SshExecError, run_command
from app.integrations.proxmox.client import ProxmoxClient
from app.integrations.proxmox.plugin import ProxmoxConfig, resolve_token_id
from app.integrations.windows_winrm.plugin import run_powershell
from app.llm.inspect_policy import (
    WINDOWS_OUTPUT_SUFFIX,
    PolicyError,
    check_linux,
    check_proxmox_path,
    check_windows,
)
from app.llm.tool_base import AgentToolError, truncate

MUTATING_TOOLS = frozenset({"apply_updates"})
"""Tools that change a host: they always wait for a human; only an agent with allow_changes may hold one."""

OS_KINDS = {"generic_ssh": "linux", "windows_winrm": "windows", "proxmox": "proxmox", "http_tcp": "web"}
UPDATE_TIMEOUT_SECONDS = 900.0
HTTP_TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 3
_HIDDEN_HEADERS = {"set-cookie", "authorization", "proxy-authorization"}
_UPDATE_COMMANDS = {
    "apt": "sudo -n apt-get -y -o Dpkg::Options::=--force-confold upgrade",
    "dnf": "sudo -n dnf -y upgrade",
}
_DETECT_MANAGER = (
    "if command -v apt-get >/dev/null; then echo apt; elif command -v dnf >/dev/null; then echo dnf; fi"
)


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_ID = {"type": "integer", "description": "integration_id from list_inspect_targets"}

SCHEMAS: list[dict[str, Any]] = [
    _schema(
        "list_inspect_targets",
        "List what you may inspect: integrations (Linux over SSH, Windows over WinRM, Proxmox) with "
        "their os_kind, "
        "the device they reach, and the web services that http_inspect can check. Read-only; no credentials.",
        {},
        [],
    ),
    _schema(
        "ssh_readonly",
        "Run ONE read-only command over SSH (check the integration's os_kind from list_inspect_targets "
        "first). On a Linux host (os_kind linux): only letters, digits and _ . / : = , @ % + - are "
        "allowed - no quotes, pipes, redirects, substitution or globbing. Allowed programs: ps ss uname "
        "uptime free df vmstat who w last lastb id getent lsmod lsblk lsof cat head tail ls stat wc du "
        "zcat sha256sum sha1sum md5sum strings find journalctl date file grep zgrep, systemctl "
        "status/list-*/is-*/show/cat, ip addr/link/route/neigh, apt list, apt-get -s, dnf/yum "
        "check-update/list/info, dpkg -l, rpm -q, crontab -l. On a Windows host (os_kind windows): one "
        "read-only Get- PowerShell cmdlet, same allowlist and syntax as winrm_readonly. Secret files are "
        "refused on either OS.",
        {"integration_id": _ID, "command": {"type": "string"}},
        ["integration_id", "command"],
    ),
    _schema(
        "winrm_readonly",
        "Run ONE read-only PowerShell Get- cmdlet on a Windows host (os_kind windows), e.g. "
        "'Get-WinEvent -LogName Security -MaxEvents 50'. No pipes, quotes, variables or script "
        "blocks; output is "
        "plain text. Only a fixed list of Get- cmdlets is allowed.",
        {"integration_id": _ID, "command": {"type": "string"}},
        ["integration_id", "command"],
    ),
    _schema(
        "proxmox_get",
        "Read a Proxmox VE API path (GET only), e.g. /nodes/pve1/status, /nodes/pve1/qemu, "
        "/nodes/pve1/tasks, "
        "/nodes/pve1/syslog, /nodes/pve1/apt/update, /cluster/resources.",
        {"integration_id": _ID, "path": {"type": "string"}},
        ["integration_id", "path"],
    ),
    _schema(
        "http_inspect",
        "Check a monitored web service: status, response headers, redirect chain and TLS certificate "
        "(subject, issuer, expiry). Only services in the inventory; GET only.",
        {"service_id": {"type": "integer", "description": "service_id from list_inspect_targets"}},
        ["service_id"],
    ),
    _schema(
        "apply_updates",
        "Install pending package updates on a Linux host (apt or dnf) over SSH with sudo. This "
        "CHANGES the host: a "
        "human must approve every call. Run ssh_readonly 'apt list --upgradable' first and say why.",
        {"integration_id": _ID},
        ["integration_id"],
    ),
]


async def _load(
    databases: Databases, integration_id: Any, type_key: str
) -> tuple[Integration, dict[str, Any]]:
    """The integration row and its decrypted credential. The caller keeps the credential local."""
    try:
        integration_id = int(integration_id)
    except (TypeError, ValueError) as exc:
        raise AgentToolError("integration_id must be a number") from exc
    async with databases.app_session_factory() as session:
        integration = await session.get(Integration, integration_id)
    if integration is None or not integration.enabled:
        raise AgentToolError(f"no enabled integration {integration_id}")
    if integration.integration_type != type_key:
        raise AgentToolError(
            f"integration {integration_id} is {integration.integration_type}, not {type_key}"
        )
    if integration.credential_id is None:
        raise AgentToolError(f"integration {integration_id} has no credential")
    try:
        async with databases.credentials_session_factory() as session:
            credential = await CredentialService(get_secret_box()).get_decrypted(
                session, integration.credential_id
            )
    except (CredentialNotFoundError, MasterKeyError) as exc:
        raise AgentToolError("the credential could not be read") from exc
    return integration, credential


async def list_inspect_targets(databases: Databases, arguments: dict[str, Any]) -> Any:
    async with databases.app_session_factory() as session:
        integrations = list(
            await session.scalars(
                select(Integration).where(
                    Integration.enabled, Integration.integration_type.in_(list(OS_KINDS) + ["proxmox"])
                )
            )
        )
        devices = {d.id: d for d in await session.scalars(select(Device))}
        services = list(
            await session.scalars(
                select(Service).where(Service.service_type.in_([ServiceType.HTTP, ServiceType.HTTPS]))
            )
        )
    targets = []
    for integration in integrations:
        kind = OS_KINDS.get(integration.integration_type)
        if kind in (None, "web") or integration.credential_id is None:
            continue
        if integration.integration_type == "generic_ssh":
            # Learned from a real poll (see generic_ssh/plugin.py's OS detection); "linux" until then.
            kind = integration.config.get("os_family") or kind
        device = devices.get(integration.config.get("device_id", -1))
        if device is None and not integration.config.get("host"):
            continue  # nothing to connect to: offering it only sends the model into "key not pinned" errors
        targets.append(
            {
                "integration_id": integration.id,
                "name": integration.name,
                "type": integration.integration_type,
                "os_kind": kind,
                "device": device.display_name if device else integration.config.get("host"),
                "ip": device.primary_ip if device else integration.config.get("host"),
            }
        )
    web = [
        {
            "service_id": s.id,
            "name": s.name,
            "url": (s.config or {}).get("url"),
            "device": devices[s.device_id].display_name if s.device_id in devices else None,
        }
        for s in services
        if (s.config or {}).get("url")
    ]
    return {"integrations": targets, "web_services": web}


def _command(arguments: dict[str, Any]) -> str:
    return str(arguments.get("command") or "")


async def ssh_readonly(databases: Databases, arguments: dict[str, Any]) -> Any:
    integration, credential = await _load(databases, arguments.get("integration_id"), "generic_ssh")
    os_family = integration.config.get("os_family") or "linux"
    remote_command: str
    if os_family == "windows":
        # Win32-OpenSSH's default remote shell is cmd.exe, so a PowerShell cmdlet needs an explicit
        # wrapper - reuses winrm_readonly's own cmdlet allowlist rather than a second one, since the
        # read-only guarantee it already enforces is the same one needed here. cmd.exe (not PowerShell)
        # parses this string first, so the "|" into Out-String must be caret-escaped or cmd.exe treats
        # it as its own pipe instead of passing it through to powershell.exe's -Command argument.
        # Unverified against a real Windows OpenSSH host - the Linux path above was live-tested today,
        # this was not; if a host's DefaultShell is PowerShell instead of the cmd.exe default, the
        # wrapper is redundant but still correct (PowerShell can invoke itself).
        try:
            command = check_windows(_command(arguments))
        except PolicyError as exc:
            raise AgentToolError(str(exc)) from exc
        remote_command = f"powershell -NoProfile -NonInteractive -Command {command} ^| Out-String -Width 200"
    else:
        try:
            command = check_linux(_command(arguments))
        except PolicyError as exc:
            raise AgentToolError(str(exc)) from exc
        remote_command = command
    try:
        status, stdout, stderr = await run_command(integration.config, credential, remote_command)
    except SshExecError as exc:
        raise AgentToolError(str(exc)) from exc
    return {"command": command, "exit_status": status, "stdout": truncate(stdout), "stderr": truncate(stderr)}


async def winrm_readonly(databases: Databases, arguments: dict[str, Any]) -> Any:
    try:
        command = check_windows(_command(arguments))
    except PolicyError as exc:
        raise AgentToolError(str(exc)) from exc
    integration, credential = await _load(databases, arguments.get("integration_id"), "windows_winrm")
    if not integration.config.get("host"):
        raise AgentToolError("this integration has no host configured yet (it's a credential wallet entry)")
    try:
        status, stdout, stderr = await run_powershell(
            integration.config, credential, command + WINDOWS_OUTPUT_SUFFIX
        )
    except Exception as exc:  # pywinrm raises requests/winrm/OS errors; none may carry the credential
        raise AgentToolError(f"winrm failed: {type(exc).__name__}") from exc
    return {"command": command, "exit_status": status, "stdout": truncate(stdout), "stderr": truncate(stderr)}


async def proxmox_get(databases: Databases, arguments: dict[str, Any]) -> Any:
    try:
        path = check_proxmox_path(str(arguments.get("path") or ""))
    except PolicyError as exc:
        raise AgentToolError(str(exc)) from exc
    integration, credential = await _load(databases, arguments.get("integration_id"), "proxmox")
    cfg = ProxmoxConfig.model_validate(integration.config)
    token_id = resolve_token_id(integration.config, credential)
    if cfg.host is None or token_id is None:
        raise AgentToolError("this integration has no host configured yet (it's a credential wallet entry)")
    client = ProxmoxClient(
        cfg.host,
        cfg.port,
        token_id,
        credential["token_secret"],
        cfg.verify_tls,
        cfg.timeout_seconds,
        cfg.tls_ca_pem,
    )
    try:
        data = await client.get(path)
    except httpx.HTTPError as exc:
        raise AgentToolError(f"proxmox request failed: {type(exc).__name__}") from exc
    return {"path": path, "data": truncate(json.dumps(data, default=str))}


async def _certificate(url: str) -> dict[str, Any] | None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # reading the certificate, not trusting it
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(parts.hostname, parts.port or 443, ssl=context), HTTP_TIMEOUT_SECONDS
        )
    except (OSError, TimeoutError):
        return None
    try:
        der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    finally:
        writer.close()
    cert = x509.load_der_x509_certificate(der)
    names: list[str] = []
    with contextlib.suppress(x509.ExtensionNotFound):
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        names = san.value.get_values_for_type(x509.DNSName)
    expires = cert.not_valid_after_utc
    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "self_signed": cert.subject == cert.issuer,
        "not_after": expires.isoformat(),
        "days_left": (expires - datetime.datetime.now(datetime.UTC)).days,
        "dns_names": names[:10],
    }


async def http_inspect(databases: Databases, arguments: dict[str, Any]) -> Any:
    try:
        service_id = int(arguments.get("service_id"))  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise AgentToolError("service_id must be a number") from exc
    async with databases.app_session_factory() as session:
        service = await session.get(Service, service_id)
    url = (service.config or {}).get("url") if service else None
    if service is None or not url:
        raise AgentToolError(f"service {service_id} is not a monitored web service")
    verify = bool((service.config or {}).get("verify_tls", True))
    chain: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS, verify=verify, follow_redirects=False
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                response = await client.get(url, headers={"User-Agent": "banana-agent"})
                chain.append({"url": url, "status": response.status_code})
                if not response.is_redirect:
                    break
                url = urljoin(url, response.headers.get("location", ""))
    except httpx.HTTPError as exc:
        raise AgentToolError(
            f"request failed: {type(exc).__name__} for {url}. The same service will fail the same way: "
            "do not retry it, report it as unreachable over HTTP(S)."
        ) from exc
    headers = {k: v for k, v in response.headers.items() if k.lower() not in _HIDDEN_HEADERS}
    return {
        "service": service.name,
        "redirects": chain,
        "status": response.status_code,
        "headers": headers,
        "tls": await _certificate(str(response.url)),
    }


async def apply_updates(databases: Databases, arguments: dict[str, Any]) -> Any:
    integration, credential = await _load(databases, arguments.get("integration_id"), "generic_ssh")
    try:
        _, manager, _ = await run_command(integration.config, credential, _DETECT_MANAGER)
        manager = manager.strip()
        if manager not in _UPDATE_COMMANDS:
            raise AgentToolError("no supported package manager (apt or dnf) found")
        async with databases.app_session_factory() as session:
            session.add(
                Event(
                    source="ai",
                    severity=EventSeverity.WARNING,
                    category="ai_change",
                    message=f"Package updates ({manager}) started by an agent on {integration.name}",
                )
            )
            await session.commit()
        status, stdout, stderr = await run_command(
            integration.config, credential, _UPDATE_COMMANDS[manager], UPDATE_TIMEOUT_SECONDS
        )
    except SshExecError as exc:
        raise AgentToolError(str(exc)) from exc
    return {
        "package_manager": manager,
        "exit_status": status,
        "stdout_tail": truncate(stdout[-3000:]),
        "stderr_tail": truncate(stderr[-1000:]),
    }


HANDLERS = {
    "list_inspect_targets": list_inspect_targets,
    "ssh_readonly": ssh_readonly,
    "winrm_readonly": winrm_readonly,
    "proxmox_get": proxmox_get,
    "http_inspect": http_inspect,
    "apply_updates": apply_updates,
}

INSPECT_TOOL_NAMES = frozenset(HANDLERS)
