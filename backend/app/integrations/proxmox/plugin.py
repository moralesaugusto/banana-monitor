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
from app.integrations.proxmox.client import ProxmoxClient
from app.integrations.tls import explain, normalize_pem


class ProxmoxConfig(BaseModel):
    host: str | None = Field(
        default=None,
        description="Leave empty to save this credential in the wallet: discovery tries it against any "
        "host it finds that looks like a Proxmox node, and auto-creates this integration on the first "
        "match. A wallet credential needs its token_id set too (see ProxmoxTokenCredential).",
    )
    port: int = Field(default=8006, description="Proxmox's default API port; change only if customized.")
    token_id: str | None = Field(
        default=None,
        description='e.g. "banana@pve!banana-token" - not secret, just an identifier. Kept here only for '
        "integrations created before token_id moved onto the credential; a value on the credential itself "
        "wins.",
    )
    verify_tls: bool = Field(
        default=True,
        description="Verify the node's TLS certificate. Proxmox commonly uses a self-signed certificate - "
        "paste it as tls_ca_pem below instead of turning this off.",
    )
    tls_ca_pem: str = Field(
        default="",
        description="The node's certificate (PEM), trusted as the only root; safer than turning verify_tls "
        "off. Get it with: openssl s_client -connect host:port </dev/null | openssl x509",
    )

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
    timeout_seconds: float = 10.0
    interval_seconds: float = 60.0


class ProxmoxTokenCredential(BaseModel):
    token_id: str | None = Field(
        default=None,
        description='e.g. "banana@pve!banana-token" (API Token name in the Proxmox UI). Required here for '
        "a wallet credential (no host, so no config.token_id to fall back on); optional otherwise.",
    )
    token_secret: str = Field(
        description="The token's secret value, shown once when you create it in Proxmox."
    )


def resolve_token_id(config: dict[str, Any], credential: dict[str, Any]) -> str | None:
    return credential.get("token_id") or config.get("token_id")


class ProxmoxPlugin:
    """Discovers Proxmox nodes/VMs/LXCs and polls their live status.

    Unlike generic_ssh, this plugin enumerates its own targets - list_targets()
    is the authoritative source of what this integration monitors, and the
    scheduler auto-provisions/reuses one Device per discovered resource.
    """

    type_key: ClassVar[str] = "proxmox"
    display_name: ClassVar[str] = "Proxmox VE"
    config_schema: ClassVar[type[BaseModel]] = ProxmoxConfig
    credential_schema: ClassVar[type[BaseModel] | None] = ProxmoxTokenCredential

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            cfg = ProxmoxConfig.model_validate(config)
        except ValueError as exc:
            return ValidationResult(ok=False, message=clean_validation_message(exc))
        if not credential or "token_secret" not in credential:
            return ValidationResult(ok=False, message="A Proxmox API token secret is required")
        if not resolve_token_id(config, credential):
            return ValidationResult(ok=False, message="A Proxmox API token id is required")
        if cfg.host is None:
            return ValidationResult(ok=True)  # a wallet entry: nothing to connect to yet
        if not await self.probe_credential(credential, cfg.host, cfg.port):
            return ValidationResult(
                ok=False,
                message=f"Could not reach or authenticate to the Proxmox API at {cfg.host}:{cfg.port} - "
                "check the host, port, token id and token secret.",
            )
        return ValidationResult(ok=True)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        if not credential:
            return []
        cfg = ProxmoxConfig.model_validate(config)
        if cfg.host is None:
            return []  # a wallet entry: nothing to poll until discovery finds it a host
        client = self._make_client(cfg, credential)

        targets: list[TargetDescriptor] = []
        for node in await client.list_nodes():
            node_name = node["node"]
            targets.append(
                TargetDescriptor(
                    external_ref=f"node:{node_name}",
                    display_name=node_name,
                    attributes={"resource_type": "node", "node": node_name, "device_type": "proxmox_node"},
                )
            )
            for vm in await client.list_qemu(node_name):
                targets.append(
                    TargetDescriptor(
                        external_ref=f"qemu:{node_name}:{vm['vmid']}",
                        display_name=vm.get("name") or f"vm-{vm['vmid']}",
                        attributes={
                            "resource_type": "qemu",
                            "node": node_name,
                            "vmid": vm["vmid"],
                            "device_type": "proxmox_vm",
                        },
                    )
                )
            for lxc in await client.list_lxc(node_name):
                targets.append(
                    TargetDescriptor(
                        external_ref=f"lxc:{node_name}:{lxc['vmid']}",
                        display_name=lxc.get("name") or f"lxc-{lxc['vmid']}",
                        attributes={
                            "resource_type": "lxc",
                            "node": node_name,
                            "vmid": lxc["vmid"],
                            "device_type": "proxmox_lxc",
                        },
                    )
                )
        return targets

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
        cfg = ProxmoxConfig.model_validate(config)
        client = self._make_client(cfg, credential)

        resource_type = target.attributes.get("resource_type")
        node = target.attributes.get("node")
        if not isinstance(node, str):
            return PollResult(success=False, error_message="Target is missing its Proxmox node")
        started = time.monotonic()
        try:
            if resource_type == "node":
                data = await client.node_status(node)
                metrics = self._node_metrics(data)
                running = True
            elif resource_type in ("qemu", "lxc"):
                vmid = target.attributes["vmid"]
                items = (
                    await client.list_qemu(node) if resource_type == "qemu" else await client.list_lxc(node)
                )
                match = next((item for item in items if item["vmid"] == vmid), None)
                if match is None:
                    return PollResult(success=False, error_message="Resource no longer present")
                metrics = self._vm_metrics(match)
                running = match.get("status") == "running"
            else:
                return PollResult(success=False, error_message=f"Unknown resource type {resource_type}")
        except httpx.HTTPError as exc:
            return PollResult(success=False, error_message=explain(exc))

        latency_ms = (time.monotonic() - started) * 1000
        return PollResult(success=running, latency_ms=latency_ms, metrics=metrics)

    def _make_client(self, cfg: ProxmoxConfig, credential: dict[str, Any]) -> ProxmoxClient:
        assert cfg.host is not None  # guaranteed: list_targets()/poll() never run for a wallet entry
        token_id = resolve_token_id(cfg.model_dump(), credential)
        assert token_id is not None  # guaranteed by validate_config()
        return ProxmoxClient(
            cfg.host,
            cfg.port,
            token_id,
            credential["token_secret"],
            cfg.verify_tls,
            cfg.timeout_seconds,
            cfg.tls_ca_pem,
        )

    async def probe_credential(self, credential: dict[str, Any], host: str, port: int = 8006) -> bool:
        """Tries this credential against host:port - used only by the credential wallet. TLS is not
        verified here (there's no pinned certificate for a host discovery hasn't configured yet); the
        resulting integration, once provisioned, defaults back to verified TLS as normal."""
        token_id = resolve_token_id({}, credential)
        if not token_id or not credential.get("token_secret"):
            return False
        client = ProxmoxClient(host, port, token_id, credential["token_secret"], False, 5.0, "")
        try:
            await client.list_nodes()
            return True
        except httpx.HTTPError:
            return False

    def _node_metrics(self, data: dict[str, Any]) -> dict[str, float]:
        metrics: dict[str, float] = {}
        cpu = data.get("cpu")
        if cpu is not None:
            metrics["cpu_percent"] = float(cpu) * 100
        memory = data.get("memory") or {}
        total = memory.get("total")
        used = memory.get("used")
        if total:
            metrics["mem_used_percent"] = used / total * 100
        return metrics

    def _vm_metrics(self, data: dict[str, Any]) -> dict[str, float]:
        metrics: dict[str, float] = {}
        cpu = data.get("cpu")
        if cpu is not None:
            metrics["cpu_percent"] = float(cpu) * 100
        maxmem = data.get("maxmem")
        mem = data.get("mem")
        if maxmem:
            metrics["mem_used_percent"] = mem / maxmem * 100
        uptime = data.get("uptime")
        if uptime is not None:
            metrics["uptime_seconds"] = float(uptime)
        return metrics
