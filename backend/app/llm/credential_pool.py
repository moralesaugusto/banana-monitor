"""Lets the host-inspection tools pick a stored credential for a host by themselves.

An agent that passes `host` (instead of an `integration_id`) gets a credential chosen in this order:
  1. an enabled integration bound to that host or its device - always first;
  2. credentials bound to the host's Network (the discovery auto-login bindings);
  3. the credential pool: credentials flagged `in_agent_pool`, plus the credentials of host-less
     ("wallet") integrations - or, for an agent set to "selected", only the credentials ticked for it.
Steps 2 and 3 only apply when the agent's `credential_scope` is not "bound".

The decrypted credential is returned to the caller as a local value; it is never logged, stored or put in
a result. The safeguards (host scope, attempt cap, SSH host-key trust, apply_updates) are on by default and
each is relaxed by its own AiModeSettings flag - see docs/decisions.md."""

import asyncio
import ipaddress
import time
from dataclasses import dataclass, field
from typing import Any

import asyncssh
from sqlalchemy import select

from app.credentials.crypto import MasterKeyError, get_secret_box
from app.credentials.models import Credential
from app.credentials.service import CredentialNotFoundError, CredentialService
from app.db.session import Databases
from app.domain.bootstrap import ensure_default_ai_mode_settings
from app.domain.enums import CredentialType, EventSeverity
from app.domain.models import (
    AiAgent,
    AiModeSettings,
    Device,
    Event,
    Integration,
    Network,
    NetworkCredentialBinding,
    SshHostKey,
)
from app.integrations import registry
from app.integrations.generic_ssh import hostkey
from app.integrations.generic_ssh.plugin import ssh_auth_kwargs
from app.llm.tool_base import AgentToolError
from app.logging_setup import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS_PER_HOST = 5
"""Rejected credentials per host (and tool kind) within MEMORY_SECONDS before the agent is stopped, so a
pool cannot lock an account or trip fail2ban. Relaxed by AiModeSettings.cred_no_attempt_limit."""
MEMORY_SECONDS = 900.0
PORT_CHECK_SECONDS = 3.0

TOOL_PORTS = {"generic_ssh": 22, "windows_winrm": 5986, "proxmox": 8006}
TOOL_CREDENTIAL_TYPES = {
    "generic_ssh": {CredentialType.SSH_KEY, CredentialType.SSH_PASSWORD},
    "windows_winrm": {CredentialType.BASIC_AUTH},
    "proxmox": {CredentialType.API_TOKEN},
}

SAFEGUARD_LABELS = {
    "cred_allow_unlisted_hosts": "credentials may be tried on hosts outside the inventory and networks",
    "cred_no_attempt_limit": "no limit on rejected credentials per host",
    "cred_trust_new_host_keys": "an unseen SSH host key is trusted on first use",
    "cred_pool_for_updates": "pool credentials may be used for apply_updates",
}

_worked: dict[tuple[str, str], tuple[int, float]] = {}
_rejected: dict[tuple[str, str, int], float] = {}


def clear_memory() -> None:
    _worked.clear()
    _rejected.clear()


def forget_worked(ip: str, type_key: str) -> None:
    """Called when a tool failed with a remembered credential, so the next call picks again."""
    _worked.pop((ip, type_key), None)


@dataclass
class Candidate:
    credential_id: int
    label: str
    source: str  # host-bound | network | pool
    integration: Integration | None = None


@dataclass
class Resolved:
    config: dict[str, Any]
    label: str
    source: str
    ip: str
    credential: dict[str, Any] = field(repr=False)
    notes: dict[str, Any] = field(default_factory=dict)


def relaxed_safeguards(settings: AiModeSettings) -> list[str]:
    return [label for flag, label in SAFEGUARD_LABELS.items() if getattr(settings, flag)]


def _fresh(stamp: float) -> bool:
    return time.monotonic() - stamp < MEMORY_SECONDS


async def _locate(databases: Databases, host: str) -> tuple[str, Device | None]:
    """An IP, or the name of a known device, to (ip, the matching Device if any)."""
    host = host.strip()
    async with databases.app_session_factory() as session:
        try:
            ip = str(ipaddress.ip_address(host))
        except ValueError:
            lowered = host.lower()
            devices = await session.scalars(select(Device))
            for known in devices:
                names = {(known.display_name or "").lower(), (known.hostname or "").lower()}
                if lowered in names and known.primary_ip:
                    return known.primary_ip, known
            raise AgentToolError(
                f"{host!r} is neither an IP address nor the name of a known device"
            ) from None
        device = await session.scalar(select(Device).where(Device.primary_ip == ip))
    return ip, device


async def _check_scope(
    databases: Databases, ip: str, device: Device | None, settings: AiModeSettings
) -> tuple[int | None, bool]:
    """Returns (containing network id, whether it is inside the inventory/configured scope)."""
    address = ipaddress.ip_address(ip)
    network_id: int | None = None
    async with databases.app_session_factory() as session:
        for net_id, cidr in (await session.execute(select(Network.id, Network.cidr))).all():
            try:
                if address in ipaddress.ip_network(cidr, strict=False):
                    network_id = net_id
                    break
            except ValueError:
                continue
    known = address.is_loopback or device is not None or network_id is not None
    if address.is_global and network_id is None:
        if not (settings.allow_undefined_network_scan and settings.allow_public_targets):
            raise AgentToolError(f"{ip} is a public address; trying credentials there is not enabled")
        if not settings.cred_allow_unlisted_hosts:
            raise AgentToolError(_unlisted_message(ip))
    elif not known and not settings.cred_allow_unlisted_hosts:
        raise AgentToolError(_unlisted_message(ip))
    return network_id, known


def _unlisted_message(ip: str) -> str:
    return (
        f"{ip} is not a known device or inside a configured network, so no stored credential is tried "
        "on it (AI Mode > Settings > Credential safeguards)"
    )


async def _candidates(
    databases: Databases,
    agent: AiAgent | None,
    type_key: str,
    ip: str,
    device: Device | None,
    network_id: int | None,
    settings: AiModeSettings,
    mutating: bool,
) -> list[Candidate]:
    types = TOOL_CREDENTIAL_TYPES[type_key]
    scope = agent.credential_scope if agent else "bound"
    selected = set(agent.credential_scope_ids or []) if agent else set()
    async with databases.app_session_factory() as session:
        integrations = list(
            await session.scalars(
                select(Integration)
                .where(
                    Integration.integration_type == type_key,
                    Integration.enabled.is_(True),
                    Integration.credential_id.is_not(None),
                )
                .order_by(Integration.id)
            )
        )
        bindings: list[int] = []
        if network_id is not None:
            rows = await session.scalars(
                select(NetworkCredentialBinding)
                .where(NetworkCredentialBinding.network_id == network_id)
                .order_by(NetworkCredentialBinding.priority, NetworkCredentialBinding.id)
            )
            bindings = [row.credential_id for row in rows]
    async with databases.credentials_session_factory() as session:
        stored = {c.id: c for c in await session.scalars(select(Credential).order_by(Credential.id))}

    def bound_here(integration: Integration) -> bool:
        cfg = integration.config
        return bool(cfg.get("host")) and (
            cfg.get("host") == ip or (device is not None and cfg.get("device_id") == device.id)
        )

    out: list[Candidate] = []
    seen: set[int] = set()

    def add(credential_id: int | None, source: str, integration: Integration | None = None) -> None:
        if credential_id is None or credential_id in seen:
            return
        row = stored.get(credential_id)
        if row is None or (source != "host-bound" and row.credential_type not in types):
            return
        seen.add(credential_id)
        out.append(Candidate(credential_id, row.label, source, integration))

    for integration in integrations:
        if bound_here(integration):
            add(integration.credential_id, "host-bound", integration)
    if scope == "bound":
        return out
    # An agent may only use a pooled credential for apply_updates if it was explicitly selected for it,
    # or the administrator relaxed that safeguard.
    if mutating and scope != "selected" and not settings.cred_pool_for_updates:
        return out

    def allowed(credential_id: int) -> bool:
        return scope != "selected" or credential_id in selected

    for credential_id in bindings:
        if allowed(credential_id):
            add(credential_id, "network")
    if scope == "selected":
        for credential_id in sorted(selected):
            add(credential_id, "pool")
    else:
        wallet = [i.credential_id for i in integrations if not i.config.get("host")]
        pooled = [cid for cid, row in stored.items() if row.in_agent_pool]
        for credential_id in sorted({*pooled, *(w for w in wallet if w is not None)}):
            add(credential_id, "pool")
    return out


async def _decrypt(databases: Databases, credential_id: int) -> dict[str, Any] | None:
    try:
        async with databases.credentials_session_factory() as session:
            return await CredentialService(get_secret_box()).get_decrypted(session, credential_id)
    except (CredentialNotFoundError, MasterKeyError):
        return None


async def _port_answers(ip: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), PORT_CHECK_SECONDS)
    except (OSError, TimeoutError):
        return False
    writer.close()
    return True


async def _trusted_key_line(databases: Databases, ip: str, port: int, relax: bool) -> str:
    """The host's current SSH key line once credentials may be sent to it. An approved key passes. An
    unseen one waits for a human unless the administrator relaxed the safeguard, in which case it is
    trusted on first use. A key that changed after approval is never trusted here."""
    try:
        line = hostkey.key_line(await hostkey.scan_host_key(ip, port, 10.0))
    except (OSError, TimeoutError) as exc:
        raise AgentToolError(f"could not read the SSH host key of {ip}:{port}") from exc
    from app.discovery.auto_login import _host_key_trusted  # local import: discovery imports the registry too

    if await _host_key_trusted(databases, ip, port, line):
        return line
    async with databases.app_session_factory() as session:
        row = await session.scalar(select(SshHostKey).where(SshHostKey.host == ip, SshHostKey.port == port))
        if relax and row is not None and not row.changed:
            row.approved = True
            await session.commit()
            return line
    raise AgentToolError(
        f"the SSH host key of {ip}:{port} is not approved (Discovery > SSH host keys); no credential was sent"
    )


def _action_config(
    type_key: str, ip: str, port: int, device: Device | None, key_line: str | None
) -> dict[str, Any]:
    device_id = device.id if device else 0
    if type_key == "generic_ssh":
        return {
            "host": ip,
            "port": port,
            "device_id": device_id,
            "host_key": key_line,
            "auto_repin_host_key": False,
        }
    if type_key == "windows_winrm":
        return {"host": ip, "port": port, "device_id": device_id, "verify_tls": False}
    return {"host": ip, "port": port, "verify_tls": False}


async def _ssh_probe(ip: str, port: int, credential: dict[str, Any], line: str) -> bool:
    """Logs in with the credential against exactly `line` (a pinned or just-approved host key), so the
    secret is never sent to a host presenting any other key."""
    try:
        auth = ssh_auth_kwargs(credential)
        username = credential["username"]
    except (asyncssh.KeyImportError, KeyError):
        return False
    try:
        async with asyncssh.connect(
            ip,
            port=port,
            username=username,
            known_hosts=hostkey.known_hosts_for(ip, port, line),
            connect_timeout=5.0,
            **auth,
        ):
            return True
    except (asyncssh.Error, OSError, TimeoutError):
        return False


async def _probe(type_key: str, ip: str, port: int, credential: dict[str, Any]) -> bool:
    plugin = registry.get_plugin(type_key)
    probe = getattr(plugin, "probe_credential", None)
    if probe is None:
        return False
    try:
        return bool(await probe(credential, ip, port))
    except (
        Exception
    ) as exc:  # a probe failure is a rejection, never an abort; nothing here carries the secret
        logger.warning("pool_probe_failed", type_key=type_key, ip=ip, error=type(exc).__name__)
        return False


async def resolve(
    databases: Databases,
    agent_name: str | None,
    type_key: str,
    host: str,
    *,
    mutating: bool = False,
    port: int | None = None,
) -> Resolved:
    """Picks, verifies and returns a credential for `host`, or raises AgentToolError saying why not."""
    ip, device = await _locate(databases, host)
    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        agent = (
            await session.scalar(select(AiAgent).where(AiAgent.name == agent_name)) if agent_name else None
        )
    network_id, _ = await _check_scope(databases, ip, device, settings)
    candidates = await _candidates(databases, agent, type_key, ip, device, network_id, settings, mutating)
    if not candidates:
        raise AgentToolError(
            f"no stored credential may be used for {type_key} on {ip}: no integration is bound to it"
            + (
                ""
                if agent is None or agent.credential_scope != "bound"
                else ", and this agent is set to host-bound integrations only"
            )
        )

    worked = _worked.get((ip, type_key))
    worked_id = worked[0] if worked and _fresh(worked[1]) else None
    rank = {"host-bound": 0, "network": 1, "pool": 2}
    candidates.sort(key=lambda c: (rank[c.source], 0 if c.credential_id == worked_id else 1))

    notes: dict[str, Any] = {}
    if relaxed := relaxed_safeguards(settings):
        notes["safeguards_relaxed"] = relaxed

    def config_for(candidate: Candidate, port: int, key_line: str | None) -> dict[str, Any]:
        base = _action_config(type_key, ip, port, device, key_line)
        if candidate.integration is not None:
            merged = {**base, **candidate.integration.config}
            if type_key == "generic_ssh" and not merged.get("host_key"):
                merged["host_key"] = key_line
            return merged
        return base

    default_port = TOOL_PORTS[type_key]
    port = port or next(
        (c.integration.config.get("port", default_port) for c in candidates if c.integration is not None),
        default_port,
    )
    if not await _port_answers(ip, port):
        raise AgentToolError(f"{ip}:{port} does not answer; no credential was tried")
    gated_line: str | None = None

    limit = None if settings.cred_no_attempt_limit else MAX_ATTEMPTS_PER_HOST
    failures = sum(1 for (h, t, _), stamp in _rejected.items() if h == ip and t == type_key and _fresh(stamp))
    tried = 0
    for candidate in candidates:
        if (ip, type_key, candidate.credential_id) in _rejected and _fresh(
            _rejected[(ip, type_key, candidate.credential_id)]
        ):
            continue
        credential = await _decrypt(databases, candidate.credential_id)
        if credential is None:
            continue
        cached = candidate.credential_id == worked_id
        pinned = candidate.integration.config.get("host_key") if candidate.integration else None
        key_line: str | None = None
        if type_key == "generic_ssh":
            if pinned:
                key_line = str(pinned)
            else:
                if gated_line is None:
                    gated_line = await _trusted_key_line(
                        databases, ip, port, settings.cred_trust_new_host_keys
                    )
                key_line = gated_line
        if not cached:
            if limit is not None and failures >= limit:
                raise AgentToolError(
                    f"{failures} credentials were already rejected by {ip} in the last "
                    f"{int(MEMORY_SECONDS // 60)} minutes; stopped to avoid locking an account "
                    "(AI Mode > Settings > Credential safeguards)"
                )
            tried += 1
            if key_line is not None:
                accepted = await _ssh_probe(ip, port, credential, key_line)
            else:
                accepted = await _probe(type_key, ip, port, credential)
            if not accepted:
                _rejected[(ip, type_key, candidate.credential_id)] = time.monotonic()
                failures += 1
                continue
            _worked[(ip, type_key)] = (candidate.credential_id, time.monotonic())
            await _record_use(databases, agent_name, candidate, ip)
        notes.update(tried=tried)
        return Resolved(
            config_for(candidate, port, key_line), candidate.label, candidate.source, ip, credential, notes
        )
    raise AgentToolError(
        f"none of the {tried or len(candidates)} stored credential(s) allowed for {type_key} "
        f"was accepted by {ip}"
    )


async def _record_use(databases: Databases, agent_name: str | None, candidate: Candidate, ip: str) -> None:
    async with databases.app_session_factory() as session:
        session.add(
            Event(
                source="ai",
                severity=EventSeverity.INFO,
                category="ai_credential_use",
                message=(
                    f"{agent_name or 'an agent'} used the {candidate.source} credential "
                    f"'{candidate.label}' on {ip}"
                ),
            )
        )
        await session.commit()


async def pool_summary(databases: Databases, agent_name: str | None) -> dict[str, Any]:
    """What list_inspect_targets tells an agent about its pool: labels and kinds, never secrets."""
    async with databases.app_session_factory() as session:
        agent = (
            await session.scalar(select(AiAgent).where(AiAgent.name == agent_name)) if agent_name else None
        )
        integrations = list(await session.scalars(select(Integration).where(Integration.enabled.is_(True))))
    scope = agent.credential_scope if agent else "bound"
    if scope == "bound":
        return {"scope": "bound", "credentials": []}
    selected = set(agent.credential_scope_ids or []) if agent else set()
    wallet = {i.credential_id for i in integrations if i.credential_id and not i.config.get("host")}
    async with databases.credentials_session_factory() as session:
        rows = list(await session.scalars(select(Credential).order_by(Credential.id)))
    usable = [
        {"label": row.label, "credential_type": str(row.credential_type)}
        for row in rows
        if (row.id in selected if scope == "selected" else row.in_agent_pool or row.id in wallet)
    ]
    return {"scope": scope, "credentials": usable}
