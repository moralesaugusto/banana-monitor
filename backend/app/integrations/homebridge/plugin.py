import time
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field, field_validator

from app.integrations.base import (
    DiscoveredItem,
    PollResult,
    TargetDescriptor,
    ValidationResult,
    clean_validation_message,
)
from app.integrations.homebridge.client import HomebridgeAuthError, HomebridgeClient


class HomebridgeConfig(BaseModel):
    device_id: int | None = Field(
        default=None, description="Link this integration to an existing Device, so metrics show up on it."
    )
    host: str | None = Field(
        default=None,
        description="Leave empty to save this credential in the wallet: discovery tries it against any "
        "host it finds that looks like this, and auto-creates this integration on the first match.",
    )
    port: int = Field(default=8581, description="Homebridge UI's default port.")
    timeout_seconds: float = 10.0
    interval_seconds: float = 60.0

    @field_validator("host", mode="before")
    @classmethod
    def _blank_host_is_none(cls, value: str | None) -> str | None:
        return value or None


class BasicAuthCredential(BaseModel):
    username: str
    password: str


# Candidate keys different Homebridge UI versions have used for the same
# underlying metric - checked in order, first match wins. Defensive by
# design: a version that reports none of these simply omits the metric
# rather than us guessing at a wrong field name.
_CPU_KEYS = ("cpuLoad", "cpu", "cpuUsage", "cpu_percent")
_MEM_KEYS = ("memoryUsage", "mem", "memUsedPercent", "mem_used_percent")


class HomebridgePlugin:
    """Homebridge UI: accessory count plus best-effort host metrics.

    One-to-one against a single instance, like generic_ssh - config accepts an
    optional device_id to link to an existing Device; list_targets() always
    returns exactly one TargetDescriptor.
    """

    type_key: ClassVar[str] = "homebridge"
    display_name: ClassVar[str] = "Homebridge"
    config_schema: ClassVar[type[BaseModel]] = HomebridgeConfig
    credential_schema: ClassVar[type[BaseModel] | None] = BasicAuthCredential

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            cfg = HomebridgeConfig.model_validate(config)
        except ValueError as exc:
            return ValidationResult(ok=False, message=clean_validation_message(exc))
        if not credential or "username" not in credential or "password" not in credential:
            return ValidationResult(ok=False, message="A Homebridge UI username and password are required")
        if cfg.host is None:
            return ValidationResult(ok=True)  # a wallet entry: nothing to reach yet

        homebridge_client = HomebridgeClient(cfg.host, cfg.port, cfg.timeout_seconds)
        try:
            async with homebridge_client.client() as client:
                await homebridge_client.login(client, credential["username"], credential["password"])
        except (httpx.HTTPError, HomebridgeAuthError) as exc:
            return ValidationResult(ok=False, message=f"Could not log in to Homebridge UI: {exc}")
        return ValidationResult(ok=True)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        cfg = HomebridgeConfig.model_validate(config)
        if cfg.host is None:
            return []  # a wallet entry: nothing to poll until discovery finds it a host
        return [
            TargetDescriptor(
                external_ref=f"homebridge:{cfg.host}:{cfg.port}",
                display_name=cfg.host,
                device_id=cfg.device_id,
            )
        ]

    async def discover(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[DiscoveredItem]:
        return []

    async def probe_credential(self, credential: dict[str, Any], host: str, port: int = 8581) -> bool:
        """Tries this credential against host:port - used only by the credential wallet."""
        if not credential.get("username") or not credential.get("password"):
            return False
        homebridge_client = HomebridgeClient(host, port)
        try:
            async with homebridge_client.client() as client:
                await homebridge_client.login(client, credential["username"], credential["password"])
            return True
        except (httpx.HTTPError, HomebridgeAuthError):
            return False

    async def poll(
        self,
        config: dict[str, Any],
        credential: dict[str, Any] | None,
        target: TargetDescriptor,
    ) -> PollResult:
        if not credential:
            return PollResult(success=False, error_message="No credential configured")
        cfg = HomebridgeConfig.model_validate(config)
        assert cfg.host is not None  # guaranteed: list_targets() never produces a target for a wallet entry
        homebridge_client = HomebridgeClient(cfg.host, cfg.port, cfg.timeout_seconds)

        started = time.monotonic()
        try:
            async with homebridge_client.client() as client:
                token = await homebridge_client.login(
                    client, credential["username"], credential["password"]
                )
                metrics = await self._collect_metrics(homebridge_client, client, token)
        except (httpx.HTTPError, HomebridgeAuthError) as exc:
            return PollResult(success=False, error_message=str(exc))

        latency_ms = (time.monotonic() - started) * 1000
        return PollResult(success=True, latency_ms=latency_ms, metrics=metrics)

    async def _collect_metrics(
        self, homebridge_client: HomebridgeClient, client: httpx.AsyncClient, token: str
    ) -> dict[str, float]:
        metrics: dict[str, float] = {}

        status_data = await homebridge_client.get_optional(client, "/api/status/homebridge", token)
        if not isinstance(status_data, dict):
            status_data = await homebridge_client.get_optional(
                client, "/api/status/server-information", token
            )
        if isinstance(status_data, dict):
            metrics.update(_extract_host_metrics(status_data))

        accessories = await homebridge_client.get_optional(client, "/api/accessories", token)
        if isinstance(accessories, list):
            metrics["accessories_total"] = float(len(accessories))

        return metrics


def _extract_host_metrics(data: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    cpu = _first_present(data, _CPU_KEYS)
    if isinstance(cpu, int | float):
        metrics["cpu_percent"] = float(cpu)
    mem = _first_present(data, _MEM_KEYS)
    if isinstance(mem, int | float):
        metrics["mem_used_percent"] = float(mem)
    return metrics


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None
