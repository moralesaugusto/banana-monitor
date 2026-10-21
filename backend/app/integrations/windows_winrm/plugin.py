import asyncio
import contextlib
import os
import tempfile
import time
from typing import Any, ClassVar

import winrm
from pydantic import BaseModel, Field, field_validator, model_validator
from requests.exceptions import RequestException
from winrm.exceptions import WinRMError

from app.integrations.base import (
    DiscoveredItem,
    PollResult,
    TargetDescriptor,
    ValidationResult,
    clean_validation_message,
)
from app.integrations.tls import explain, normalize_pem
from app.integrations.windows_winrm import parsers
from app.integrations.windows_winrm.commands import HEALTH_SCRIPT


class WindowsWinrmConfig(BaseModel):
    device_id: int | None = Field(
        default=None,
        description="Link this integration to an existing Device, so metrics show up on it. Must be set "
        "together with host, or both left empty for a wallet entry.",
    )
    host: str | None = Field(
        default=None,
        description="Leave empty (with device_id) to save this credential in the wallet: discovery tries "
        "it against any host it finds that looks like this, and auto-creates this integration on the "
        "first match.",
    )
    port: int = Field(default=5986, description="WinRM HTTPS port. Plain HTTP (5985) is not supported.")
    verify_tls: bool = Field(
        default=False,
        description="Verify the certificate against a trusted root. Off by default: Windows machines on "
        "a home LAN self-generate their own WinRM certificate with no shared CA, so there is usually "
        "nothing to verify against. Turn this on (with tls_ca_pem) only if the host has a real, "
        "stable certificate worth pinning.",
    )
    tls_ca_pem: str = Field(
        default="", description="The host's certificate (PEM), trusted as the only root. Only useful "
        "with verify_tls on; a self-generated certificate that changes if the host ever regenerates it "
        "is not worth pinning."
    )
    timeout_seconds: float = 15.0
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

    @model_validator(mode="after")
    def _host_and_device_together(self) -> "WindowsWinrmConfig":
        if (self.host is None) != (self.device_id is None):
            raise ValueError("host and device_id must both be set, or both left unset for a wallet entry")
        return self


class WindowsPasswordCredential(BaseModel):
    username: str
    password: str


def _run_powershell_sync(
    config: WindowsWinrmConfig, credential: dict[str, Any], script: str
) -> tuple[int, str, str]:
    ca_file: str | None = None
    try:
        kwargs: dict[str, Any] = {"server_cert_validation": "validate" if config.verify_tls else "ignore"}
        if config.tls_ca_pem:
            handle, ca_file = tempfile.mkstemp(suffix=".pem")
            with os.fdopen(handle, "w") as f:
                f.write(normalize_pem(config.tls_ca_pem))
            kwargs.update(server_cert_validation="validate", ca_trust_path=ca_file)
        session = winrm.Session(
            f"https://{config.host}:{config.port}/wsman",
            auth=(credential["username"], credential["password"]),
            transport="ntlm",
            read_timeout_sec=int(config.timeout_seconds) + 5,
            operation_timeout_sec=int(config.timeout_seconds),
            **kwargs,
        )
        result = session.run_ps(script)
        stdout = result.std_out.decode(errors="replace")
        return result.status_code, stdout, result.std_err.decode(errors="replace")
    finally:
        if ca_file:
            with contextlib.suppress(OSError):
                os.unlink(ca_file)


async def run_powershell(
    config: dict[str, Any], credential: dict[str, Any], script: str
) -> tuple[int, str, str]:
    """Runs `script` over WinRM (HTTPS, NTLM): a fixed script, or one the command policy accepted."""
    cfg = WindowsWinrmConfig.model_validate(config)
    return await asyncio.to_thread(_run_powershell_sync, cfg, credential, script)


class WindowsWinrmPlugin:
    """Agentless Windows health over WinRM. Read-only by construction: a poll runs one fixed script."""

    type_key: ClassVar[str] = "windows_winrm"
    display_name: ClassVar[str] = "Windows (WinRM)"
    config_schema: ClassVar[type[BaseModel]] = WindowsWinrmConfig
    credential_schema: ClassVar[type[BaseModel] | None] = WindowsPasswordCredential

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            cfg = WindowsWinrmConfig.model_validate(config)
        except ValueError as exc:
            return ValidationResult(ok=False, message=clean_validation_message(exc))
        if not credential or "username" not in credential or "password" not in credential:
            return ValidationResult(ok=False, message="A Windows username and password are required")
        if cfg.host is None:
            return ValidationResult(ok=True)  # a wallet entry: nothing to connect to yet
        if not await self.probe_credential(credential, cfg.host, cfg.port):
            return ValidationResult(
                ok=False,
                message=f"Could not connect or authenticate to {cfg.host}:{cfg.port} over WinRM - "
                "check the host, port, username and password, and that the WinRM HTTPS listener is up.",
            )
        return ValidationResult(ok=True)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        cfg = WindowsWinrmConfig.model_validate(config)
        if cfg.host is None:
            return []  # a wallet entry: nothing to poll until discovery finds it a host
        return [
            TargetDescriptor(
                external_ref=str(cfg.device_id), display_name=cfg.host, device_id=cfg.device_id
            )
        ]

    async def discover(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[DiscoveredItem]:
        return []

    async def probe_credential(self, credential: dict[str, Any], host: str, port: int = 5986) -> bool:
        """Tries this credential against host:port - used only by the credential wallet. Runs the same
        fixed, read-only health script a real poll runs; never a string built from input."""
        if not credential.get("username") or not credential.get("password"):
            return False
        # device_id is a placeholder: run_powershell/_run_powershell_sync never read it, but the config
        # model requires host and device_id to be set together (see _host_and_device_together).
        probe_config = {
            "device_id": 0, "host": host, "port": port, "verify_tls": False, "timeout_seconds": 5.0
        }
        try:
            status, _stdout, _stderr = await run_powershell(probe_config, credential, HEALTH_SCRIPT)
        except (WinRMError, RequestException, OSError, KeyError, ValueError):
            return False
        return status == 0

    async def poll(
        self,
        config: dict[str, Any],
        credential: dict[str, Any] | None,
        target: TargetDescriptor,
    ) -> PollResult:
        if not credential:
            return PollResult(success=False, error_message="No credential configured")
        started = time.monotonic()
        try:
            status, stdout, stderr = await run_powershell(config, credential, HEALTH_SCRIPT)
        except (WinRMError, RequestException, OSError, KeyError) as exc:
            return PollResult(success=False, error_message=explain(exc))
        if status != 0:
            message = stderr.strip()[:300] or f"exit status {status}"
            return PollResult(success=False, error_message=message)
        metrics, hostname = parsers.parse_health(stdout)
        return PollResult(
            success=True,
            latency_ms=(time.monotonic() - started) * 1000,
            metrics=metrics,
            hostname=hostname,
        )
