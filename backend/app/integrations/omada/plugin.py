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
from app.integrations.omada.client import OmadaApiError, OmadaClient
from app.integrations.tls import explain, normalize_pem

# Device "status" values various Omada controller versions have used to mean
# "connected/online". Best-effort - see docs/integrations.md's known
# limitation note on this plugin's field names being unverified against live
# infrastructure.
_ONLINE_STATUS_MARKERS = {1, "1", "connected", "online"}


class OmadaConfig(BaseModel):
    device_id: int | None = Field(
        default=None, description="Link this integration to an existing Device, so metrics show up on it."
    )
    host: str | None = Field(
        default=None,
        description="Leave empty to save this credential in the wallet: discovery tries it against any "
        "host it finds that looks like this, and auto-creates this integration on the first match.",
    )
    port: int = Field(default=8043, description="Omada's default HTTPS management port.")
    verify_tls: bool = Field(
        default=True,
        description="Verify the certificate. For a self-signed controller, set tls_ca_pem instead of "
        "turning this off.",
    )
    tls_ca_pem: str = Field(
        default="", description="The controller's certificate (PEM), trusted as the only root."
    )
    site: str = Field(
        default="Default", description="The Omada site name to monitor - most home controllers have just one."
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


class OmadaPlugin:
    """TP-Link Omada SDN Controller (local/standard controller): logs in via
    the controller's API v2 session endpoint, resolves the configured site
    name to its internal site id, and polls a best-effort dashboard/device
    summary for client and device counts.

    One-to-one against a single controller, like generic_ssh - config accepts
    an optional device_id to link to an existing Device; list_targets()
    always returns exactly one TargetDescriptor.

    **Known limitation:** Omada's exact Local/Standard Controller API v2
    response shapes vary by controller firmware version and were not
    verified against live infrastructure while building this plugin - see
    docs/integrations.md. Every response is validated defensively
    (OmadaClient._unwrap/_extract_list) and any unexpected shape becomes a
    clean poll failure with a clear error_message rather than a raised
    exception or a wrong metric.
    """

    type_key: ClassVar[str] = "omada"
    display_name: ClassVar[str] = "TP-Link Omada Controller"
    config_schema: ClassVar[type[BaseModel]] = OmadaConfig
    credential_schema: ClassVar[type[BaseModel] | None] = BasicAuthCredential

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            cfg = OmadaConfig.model_validate(config)
        except ValueError as exc:
            return ValidationResult(ok=False, message=clean_validation_message(exc))
        if not credential or "username" not in credential or "password" not in credential:
            return ValidationResult(
                ok=False, message="An Omada controller username and password are required"
            )
        if cfg.host is None:
            return ValidationResult(ok=True)  # a wallet entry: nothing to reach yet

        omada_client = self._make_client(cfg)
        try:
            async with omada_client.client() as client:
                await omada_client.login(client, credential["username"], credential["password"])
        except (httpx.HTTPError, OmadaApiError) as exc:
            message = f"Could not log in to the Omada controller: {explain(exc)}"
            return ValidationResult(ok=False, message=message)
        return ValidationResult(ok=True)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        cfg = OmadaConfig.model_validate(config)
        if cfg.host is None:
            return []  # a wallet entry: nothing to poll until discovery finds it a host
        return [
            TargetDescriptor(
                external_ref=f"omada:{cfg.host}:{cfg.port}",
                display_name=cfg.host,
                device_id=cfg.device_id,
            )
        ]

    async def discover(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[DiscoveredItem]:
        return []

    async def probe_credential(self, credential: dict[str, Any], host: str, port: int = 8043) -> bool:
        """Tries this credential against host:port - used only by the credential wallet. TLS is not
        verified here, same trade-off as proxmox's probe_credential."""
        if not credential.get("username") or not credential.get("password"):
            return False
        omada_client = OmadaClient(host, port, verify_tls=False)
        try:
            async with omada_client.client() as client:
                await omada_client.login(client, credential["username"], credential["password"])
            return True
        except (httpx.HTTPError, OmadaApiError):
            return False

    async def poll(
        self,
        config: dict[str, Any],
        credential: dict[str, Any] | None,
        target: TargetDescriptor,
    ) -> PollResult:
        if not credential:
            return PollResult(success=False, error_message="No credential configured")
        cfg = OmadaConfig.model_validate(config)
        omada_client = self._make_client(cfg)

        started = time.monotonic()
        try:
            async with omada_client.client() as client:
                token = await omada_client.login(client, credential["username"], credential["password"])
                site_id = await omada_client.resolve_site_id(client, token, cfg.site)
                metrics = await self._collect_metrics(omada_client, client, token, site_id)
        except (httpx.HTTPError, OmadaApiError) as exc:
            return PollResult(success=False, error_message=explain(exc))

        latency_ms = (time.monotonic() - started) * 1000
        return PollResult(success=True, latency_ms=latency_ms, metrics=metrics)

    async def _collect_metrics(
        self, omada_client: OmadaClient, client: httpx.AsyncClient, token: str, site_id: str
    ) -> dict[str, float]:
        metrics: dict[str, float] = {}

        try:
            overview = await omada_client.dashboard_overview(client, token, site_id)
        except OmadaApiError:
            overview = {}

        clients_total = overview.get("clientNum")
        if not isinstance(clients_total, int | float):
            wireless = overview.get("numWirelessClient")
            wired = overview.get("numWiredClient")
            if isinstance(wireless, int | float) or isinstance(wired, int | float):
                clients_total = (wireless or 0) + (wired or 0)
        if isinstance(clients_total, int | float):
            metrics["clients_total"] = float(clients_total)

        devices_online = overview.get("connectedDeviceNum")
        if isinstance(devices_online, int | float):
            metrics["devices_online"] = float(devices_online)
        else:
            # Fall back to counting the device list directly if the dashboard
            # summary didn't have a usable field.
            try:
                devices = await omada_client.list_devices(client, token, site_id)
            except OmadaApiError:
                devices = []
            online = [d for d in devices if d.get("status") in _ONLINE_STATUS_MARKERS]
            if devices:
                metrics["devices_online"] = float(len(online))

        return metrics

    def _make_client(self, cfg: OmadaConfig) -> OmadaClient:
        assert cfg.host is not None  # guaranteed by callers: never invoked for a wallet entry
        return OmadaClient(cfg.host, cfg.port, cfg.verify_tls, cfg.timeout_seconds, cfg.tls_ca_pem)
