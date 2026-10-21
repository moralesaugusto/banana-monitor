import asyncio
import contextlib
import ssl
import time
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, model_validator

from app.integrations.base import (
    DiscoveredItem,
    PollResult,
    TargetDescriptor,
    ValidationResult,
    clean_validation_message,
)


def _is_certificate_error(exc: httpx.HTTPError) -> bool:
    return "CERTIFICATE_VERIFY_FAILED" in str(exc) or isinstance(exc.__cause__, ssl.SSLCertVerificationError)


def _certificate_reason(message: str) -> str:
    """`[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate (_ssl.c:1010)`
    -> `self-signed certificate`."""
    return message.split("certificate verify failed:")[-1].split("(_ssl")[0].strip() or "verification failed"


class HttpTcpConfig(BaseModel):
    url: str | None = None
    host: str | None = None
    port: int | None = None
    timeout_seconds: float = 5.0
    interval_seconds: float = 30.0
    expected_status: int | None = None
    verify_tls: bool = True

    @model_validator(mode="after")
    def _require_target(self) -> "HttpTcpConfig":
        if not self.url and not (self.host and self.port):
            raise ValueError("Provide either 'url' (HTTP/HTTPS) or 'host' and 'port' (TCP)")
        if self.url:
            parts = urlsplit(self.url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ValueError("'url' must be a full http:// or https:// address")
        if self.port is not None and not 1 <= self.port <= 65535:
            raise ValueError("'port' must be between 1 and 65535")
        return self


class HttpTcpPlugin:
    type_key: ClassVar[str] = "http_tcp"
    display_name: ClassVar[str] = "HTTP/HTTPS & TCP Check"
    config_schema: ClassVar[type[BaseModel]] = HttpTcpConfig
    credential_schema: ClassVar[type[BaseModel] | None] = None

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            HttpTcpConfig.model_validate(config)
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
        cfg = HttpTcpConfig.model_validate(config)
        if cfg.url:
            return await self._poll_http(cfg)
        return await self._poll_tcp(cfg)

    async def _poll_http(self, cfg: HttpTcpConfig) -> PollResult:
        started = time.monotonic()
        untrusted: str | None = None
        try:
            response = await self._get(cfg, verify=cfg.verify_tls)
        except httpx.HTTPError as exc:
            if not (cfg.verify_tls and _is_certificate_error(exc)):
                return PollResult(success=False, error_message=str(exc))
            # Most LAN devices (routers, controllers, hypervisors) use self-signed certificates. An
            # untrusted certificate is not an outage: look again without verification to see whether the
            # service answers, and report the certificate problem as a note instead of marking it down.
            untrusted = str(exc)
            try:
                response = await self._get(cfg, verify=False)
            except httpx.HTTPError as retry_exc:
                return PollResult(success=False, error_message=str(retry_exc))

        latency_ms = (time.monotonic() - started) * 1000
        if cfg.expected_status is not None:
            success = response.status_code == cfg.expected_status
        else:
            success = 200 <= response.status_code < 400

        error = None if success else f"unexpected status code {response.status_code}"
        if success and untrusted:
            error = f"Responding, but the certificate is not trusted ({_certificate_reason(untrusted)})"
        return PollResult(success=success, latency_ms=latency_ms, error_message=error)

    async def _get(self, cfg: HttpTcpConfig, verify: bool) -> httpx.Response:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds, verify=verify) as client:
            return await client.get(cfg.url)  # type: ignore[arg-type]

    async def _poll_tcp(self, cfg: HttpTcpConfig) -> PollResult:
        started = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(cfg.host, cfg.port), timeout=cfg.timeout_seconds
            )
        except (TimeoutError, OSError) as exc:
            return PollResult(success=False, error_message=str(exc))

        latency_ms = (time.monotonic() - started) * 1000
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        return PollResult(success=True, latency_ms=latency_ms)
