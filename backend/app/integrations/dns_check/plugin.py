import time
from typing import Any, ClassVar

import dns.asyncresolver
import dns.exception
from pydantic import BaseModel

from app.integrations.base import (
    DiscoveredItem,
    PollResult,
    TargetDescriptor,
    ValidationResult,
    clean_validation_message,
)


class DnsCheckConfig(BaseModel):
    host: str
    port: int = 53
    query_name: str = "example.com"
    """Name to resolve on every poll. Defaults to a stable, always-resolvable
    public domain so a check works out of the box against any recursive
    resolver without requiring the user to own a zone the target serves.
    Override this to something the target authoritatively serves (a LAN
    hostname, a local zone) to also exercise local/conditional-forwarding
    resolution rather than just "can this resolver reach the internet"."""
    record_type: str = "A"
    timeout_seconds: float = 5.0
    interval_seconds: float = 30.0


class DnsCheckPlugin:
    """Generic DNS resolution check: queries `query_name`/`record_type` directly
    against `host:port` and reports success if it resolves within the timeout.

    Service-backed like http_tcp - no credential, no Device auto-provisioning.
    Scheduled per-Service via SERVICE_TYPE_TO_PLUGIN (ServiceType.DNS).
    """

    type_key: ClassVar[str] = "dns"
    display_name: ClassVar[str] = "DNS Resolution Check"
    config_schema: ClassVar[type[BaseModel]] = DnsCheckConfig
    credential_schema: ClassVar[type[BaseModel] | None] = None

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            DnsCheckConfig.model_validate(config)
        except ValueError as exc:
            return ValidationResult(ok=False, message=clean_validation_message(exc))
        return ValidationResult(ok=True)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        return []

    async def discover(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[DiscoveredItem]:
        return []

    async def poll(
        self,
        config: dict[str, Any],
        credential: dict[str, Any] | None,
        target: TargetDescriptor,
    ) -> PollResult:
        cfg = DnsCheckConfig.model_validate(config)
        resolver = dns.asyncresolver.Resolver(configure=False)
        resolver.nameservers = [cfg.host]
        resolver.port = cfg.port

        started = time.monotonic()
        try:
            await resolver.resolve(cfg.query_name, cfg.record_type, lifetime=cfg.timeout_seconds)
        except dns.exception.DNSException as exc:
            return PollResult(success=False, error_message=str(exc))
        except OSError as exc:
            return PollResult(success=False, error_message=str(exc))

        latency_ms = (time.monotonic() - started) * 1000
        return PollResult(success=True, latency_ms=latency_ms, metrics={"response_time_ms": latency_ms})
