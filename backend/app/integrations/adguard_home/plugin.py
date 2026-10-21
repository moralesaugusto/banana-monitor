import time
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field, field_validator

from app.integrations.adguard_home.client import AdGuardHomeClient
from app.integrations.base import (
    DiscoveredItem,
    PollResult,
    TargetDescriptor,
    ValidationResult,
    clean_validation_message,
)
from app.integrations.tls import explain, normalize_pem


class AdGuardHomeConfig(BaseModel):
    device_id: int | None = Field(
        default=None, description="Link this integration to an existing Device, so metrics show up on it."
    )
    host: str | None = Field(
        default=None,
        description="Leave empty to save this credential in the wallet: discovery tries it against any "
        "host it finds that looks like this, and auto-creates this integration on the first match.",
    )
    port: int = Field(default=3000, description="AdGuard Home's default web UI/API port.")
    verify_tls: bool = Field(
        default=True,
        description="Verify the certificate. For a self-signed device, set tls_ca_pem instead of turning "
        "this off.",
    )
    use_https: bool = Field(
        default=False,
        description="AdGuard's own port (3000) is plain HTTP; turn this on if you've fronted it with TLS "
        "yourself. A pinned certificate or a well-known HTTPS port (443, 8443) also selects https "
        "automatically.",
    )
    tls_ca_pem: str = Field(
        default="",
        description="The device's certificate (PEM), trusted as the only root. Get it with: "
        "openssl s_client -connect host:port </dev/null | openssl x509",
    )
    timeout_seconds: float = 10.0
    interval_seconds: float = 60.0

    @field_validator("host", mode="before")
    @classmethod
    def _blank_host_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("tls_ca_pem")
    @classmethod
    def _is_a_certificate(cls, value: str) -> str:
        if value:
            normalize_pem(value)
        return value


class BasicAuthCredential(BaseModel):
    username: str
    password: str


class AdGuardHomePlugin:
    """AdGuard Home DNS filtering: reachability plus query/blocking stats.

    One-to-one against a single instance, like generic_ssh - config accepts an
    optional device_id to link to an existing Device; list_targets() always
    returns exactly one TargetDescriptor.
    """

    type_key: ClassVar[str] = "adguard_home"
    display_name: ClassVar[str] = "AdGuard Home"
    config_schema: ClassVar[type[BaseModel]] = AdGuardHomeConfig
    credential_schema: ClassVar[type[BaseModel] | None] = BasicAuthCredential

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            cfg = AdGuardHomeConfig.model_validate(config)
        except ValueError as exc:
            return ValidationResult(ok=False, message=clean_validation_message(exc))
        if not credential or "username" not in credential or "password" not in credential:
            return ValidationResult(ok=False, message="An AdGuard Home username and password are required")
        if cfg.host is None:
            return ValidationResult(ok=True)  # a wallet entry: nothing to reach yet

        client = self._make_client(cfg, credential)
        try:
            await client.status()
        except httpx.HTTPError as exc:
            return ValidationResult(ok=False, message=f"Could not reach AdGuard Home: {explain(exc)}")
        return ValidationResult(ok=True)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        cfg = AdGuardHomeConfig.model_validate(config)
        if cfg.host is None:
            return []  # a wallet entry: nothing to poll until discovery finds it a host
        return [
            TargetDescriptor(
                external_ref=f"adguard_home:{cfg.host}:{cfg.port}",
                display_name=cfg.host,
                device_id=cfg.device_id,
            )
        ]

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
        if not credential:
            return PollResult(success=False, error_message="No credential configured")
        cfg = AdGuardHomeConfig.model_validate(config)
        client = self._make_client(cfg, credential)

        started = time.monotonic()
        try:
            status = await client.status()
            stats = await client.stats()
        except httpx.HTTPError as exc:
            return PollResult(success=False, error_message=explain(exc))
        latency_ms = (time.monotonic() - started) * 1000

        metrics: dict[str, float] = {}
        queries_total = stats.get("num_dns_queries")
        blocked = stats.get("num_blocked_filtering")
        if isinstance(queries_total, int | float):
            metrics["queries_total"] = float(queries_total)
            if queries_total and isinstance(blocked, int | float):
                metrics["blocked_percent"] = float(blocked) / float(queries_total) * 100
        avg_processing_time = stats.get("avg_processing_time")
        if isinstance(avg_processing_time, int | float):
            # AdGuard Home reports this in seconds.
            metrics["avg_processing_time_ms"] = float(avg_processing_time) * 1000
        if isinstance(status.get("protection_enabled"), bool):
            metrics["protection_enabled"] = 1.0 if status["protection_enabled"] else 0.0

        return PollResult(success=True, latency_ms=latency_ms, metrics=metrics)

    async def probe_credential(self, credential: dict[str, Any], host: str, port: int = 3000) -> bool:
        """Tries this credential against host:port - used only by the credential wallet. TLS is not
        verified here, same trade-off as proxmox's probe_credential."""
        if not credential.get("username") or not credential.get("password"):
            return False
        client = AdGuardHomeClient(
            host, port, credential["username"], credential["password"], verify_tls=False
        )
        try:
            await client.status()
            return True
        except httpx.HTTPError:
            return False

    def _make_client(self, cfg: AdGuardHomeConfig, credential: dict[str, Any]) -> AdGuardHomeClient:
        assert cfg.host is not None  # guaranteed by callers: never invoked for a wallet entry
        return AdGuardHomeClient(
            cfg.host, cfg.port, credential["username"], credential["password"], cfg.verify_tls,
            cfg.timeout_seconds,
            use_https=cfg.use_https,
            ca_pem=cfg.tls_ca_pem,
        )
