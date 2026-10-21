import re
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from app.integrations.base import (
    DiscoveredItem,
    PollResult,
    TargetDescriptor,
    ValidationResult,
    clean_validation_message,
)

_API_KEY = re.compile(r"^[0-9a-fA-F]{64}$")
_PROBE_TIMEOUT_SECONDS = 10.0
_PROBE_URL = "https://www.virustotal.com/api/v3/ip_addresses/8.8.8.8"
"""A public, heavily-cached indicator - this is a real VirusTotal call (confirms the key actually works,
not just its shape), but one that never costs a fresh analysis and is cheap against the free tier's rate
limit."""


class VirusTotalConfig(BaseModel):
    requests_per_minute: int = Field(default=4, ge=1, le=1000)
    requests_per_day: int = Field(default=500, ge=1, le=1_000_000)
    """The free public API allows 4 a minute and 500 a day; raise both for a paid key."""


class VirusTotalCredential(BaseModel):
    api_key: str


class VirusTotalPlugin:
    """Holds the VirusTotal API key and rate limits for the `virustotal_lookup` agent tool
    (llm/virustotal_tool.py).

    It monitors nothing, so nothing polls and nothing leaves the host unless an agent that holds the tool asks
    (and the internet kill switch is off)."""

    type_key: ClassVar[str] = "virustotal"
    display_name: ClassVar[str] = "VirusTotal (agent lookups)"
    config_schema: ClassVar[type[BaseModel]] = VirusTotalConfig
    credential_schema: ClassVar[type[BaseModel] | None] = VirusTotalCredential

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            VirusTotalConfig.model_validate(config)
        except ValueError as exc:
            return ValidationResult(ok=False, message=clean_validation_message(exc))
        if not credential or not _API_KEY.match(str(credential.get("api_key", ""))):
            return ValidationResult(ok=False, message="A VirusTotal API key (64 hex characters) is required")
        if not await self.verify_api_key(credential):
            return ValidationResult(
                ok=False,
                message="Could not verify this API key with VirusTotal - check it was copied correctly "
                "and has not been revoked.",
            )
        return ValidationResult(ok=True)

    async def verify_api_key(self, credential: dict[str, Any]) -> bool:
        """A real call against VirusTotal - confirms the key actually works, not just that it looks like
        one. See _PROBE_URL for why this specific indicator is safe to call on every validation."""
        api_key = str(credential.get("api_key", ""))
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
                response = await client.get(_PROBE_URL, headers={"x-apikey": api_key})
        except httpx.HTTPError:
            return False
        return response.status_code in (200, 404)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        return []

    async def discover(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[DiscoveredItem]:
        return []

    async def poll(
        self, config: dict[str, Any], credential: dict[str, Any] | None, target: TargetDescriptor
    ) -> PollResult:
        return PollResult(success=True)
