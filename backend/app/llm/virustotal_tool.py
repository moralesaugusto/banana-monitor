"""`virustotal_lookup`: looks a file hash, public IP address or public domain up on VirusTotal.

Only identifiers are sent, never files, URLs or local names: a hash, a global IP or a domain with a public
suffix. Calls are rate limited to the integration's configured limits and cached for an hour, and each one
leaves an outbound event. The internet kill switch covers it (agent_tools.WEB_TOOL_NAMES)."""

import collections
import ipaddress
import re
import time
from typing import Any

import httpx
from sqlalchemy import select

from app.credentials.crypto import MasterKeyError, get_secret_box
from app.credentials.service import CredentialNotFoundError, CredentialService
from app.db.session import Databases
from app.domain.enums import EventSeverity
from app.domain.models import Event, Integration
from app.integrations.virustotal.plugin import VirusTotalConfig
from app.llm.tool_base import AgentToolError

BASE_URL = "https://www.virustotal.com/api/v3"
TIMEOUT_SECONDS = 15.0
CACHE_SECONDS = 3600.0
_HASH = re.compile(r"^([0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_PRIVATE_SUFFIXES = (
    "local", "lan", "home", "internal", "localdomain", "corp", "intranet", "private", "test", "invalid",
    "localhost", "arpa", "example",
)  # fmt: skip
_PATHS = {"file_hash": "files", "ip": "ip_addresses", "domain": "domains"}
_GUI = {"file_hash": "file", "ip": "ip-address", "domain": "domain"}

SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "virustotal_lookup",
        "description": (
            "Ask VirusTotal about a file hash (md5, sha1, sha256), a PUBLIC IP address or a PUBLIC "
            "domain, e.g. "
            "to check an indicator you found. Sends only that value to the internet. Private addresses and "
            "internal names are refused. Rate limited."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(_PATHS)},
                "value": {"type": "string"},
            },
            "required": ["kind", "value"],
        },
    },
}


class _Limiter:
    """Sliding windows over the last minute and the last day."""

    def __init__(self) -> None:
        self.calls: collections.deque[float] = collections.deque()
        self.cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    def clear(self) -> None:
        self.calls.clear()
        self.cache.clear()

    def take(self, per_minute: int, per_day: int) -> None:
        now = time.monotonic()
        while self.calls and now - self.calls[0] > 86400:
            self.calls.popleft()
        if len(self.calls) >= per_day:
            raise AgentToolError("VirusTotal daily limit reached")
        if sum(1 for t in self.calls if now - t <= 60) >= per_minute:
            raise AgentToolError("VirusTotal per-minute limit reached; try again in a minute")
        self.calls.append(now)


limiter = _Limiter()


def check_value(kind: str, value: str) -> str:
    value = value.strip()
    if kind == "file_hash":
        if not _HASH.match(value):
            raise AgentToolError("file_hash must be an md5, sha1 or sha256 hex digest")
        return value.lower()
    if kind == "ip":
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise AgentToolError("not an IP address") from exc
        if not address.is_global:
            raise AgentToolError("refusing to send a private, loopback or reserved address to the internet")
        return str(address)
    if kind == "domain":
        domain = value.lower().rstrip(".")
        if not _DOMAIN.match(domain) or domain.rsplit(".", 1)[-1] in _PRIVATE_SUFFIXES:
            raise AgentToolError("refusing: not a public domain name")
        return domain
    raise AgentToolError(f"kind must be one of: {', '.join(_PATHS)}")


def summarize(kind: str, attributes: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "file_hash": ("meaningful_name", "type_description", "size", "first_submission_date", "names"),
        "ip": ("country", "as_owner", "asn", "network"),
        "domain": ("registrar", "creation_date", "categories", "tld"),
    }[kind]
    summary = {k: attributes[k] for k in keep if k in attributes}
    summary["analysis"] = attributes.get("last_analysis_stats", {})
    summary["reputation"] = attributes.get("reputation")
    summary["last_analysis_date"] = attributes.get("last_analysis_date")
    classification = (attributes.get("popular_threat_classification") or {}).get("suggested_threat_label")
    if classification:
        summary["suggested_threat_label"] = classification
    return summary


async def _load_integration(databases: Databases) -> tuple[VirusTotalConfig, str]:
    async with databases.app_session_factory() as session:
        integration = await session.scalar(
            select(Integration).where(Integration.integration_type == "virustotal", Integration.enabled)
        )
    if integration is None or integration.credential_id is None:
        raise AgentToolError("VirusTotal is not configured: add the VirusTotal integration with an API key")
    try:
        async with databases.credentials_session_factory() as session:
            credential = await CredentialService(get_secret_box()).get_decrypted(
                session, integration.credential_id
            )
    except (CredentialNotFoundError, MasterKeyError) as exc:
        raise AgentToolError("the VirusTotal credential could not be read") from exc
    return VirusTotalConfig.model_validate(integration.config), str(credential["api_key"])


async def virustotal_lookup(databases: Databases, arguments: dict[str, Any]) -> Any:
    kind = str(arguments.get("kind") or "")
    value = check_value(kind, str(arguments.get("value") or ""))
    cached = limiter.cache.get((kind, value))
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return {**cached[1], "cached": True}

    config, api_key = await _load_integration(databases)
    limiter.take(config.requests_per_minute, config.requests_per_day)
    async with databases.app_session_factory() as session:
        session.add(
            Event(
                source="ai",
                severity=EventSeverity.INFO,
                category="outbound",
                message=f"VirusTotal lookup ({kind}) sent to www.virustotal.com",
            )
        )
        await session.commit()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(f"{BASE_URL}/{_PATHS[kind]}/{value}", headers={"x-apikey": api_key})
    except httpx.HTTPError as exc:
        raise AgentToolError(f"VirusTotal request failed: {type(exc).__name__}") from exc
    if response.status_code == 404:
        result: dict[str, Any] = {"found": False, "kind": kind, "value": value}
    elif response.status_code in (401, 403):
        raise AgentToolError("VirusTotal rejected the API key")
    elif response.status_code == 429:
        raise AgentToolError("VirusTotal rate limit hit")
    elif response.status_code != 200:
        raise AgentToolError(f"VirusTotal answered HTTP {response.status_code}")
    else:
        attributes = response.json().get("data", {}).get("attributes", {})
        result = {
            "found": True,
            "kind": kind,
            "value": value,
            **summarize(kind, attributes),
            "link": f"https://www.virustotal.com/gui/{_GUI[kind]}/{value}",
        }
    limiter.cache[(kind, value)] = (time.monotonic(), result)
    return result
