import time
from typing import Any, ClassVar

import asyncssh
from pydantic import BaseModel, Field, field_validator, model_validator

from app.integrations.base import (
    DiscoveredItem,
    PollResult,
    TargetDescriptor,
    ValidationResult,
    clean_validation_message,
)
from app.integrations.generic_ssh import hostkey, parsers
from app.integrations.generic_ssh.commands import COMMANDS_BY_OS, DETECT_OS_COMMAND, LINUX_COMMANDS
from app.logging_setup import get_logger

logger = get_logger(__name__)


class GenericSshConfig(BaseModel):
    device_id: int | None = None
    host: str | None = Field(
        default=None,
        description="Leave empty to save this credential in the wallet: discovery tries it against any "
        "SSH-open host it finds, and auto-creates this integration on the first match.",
    )
    port: int = 22
    timeout_seconds: float = 10.0
    interval_seconds: float = 60.0
    host_key: str | None = None
    """The host's public key, pinned on the first connection. Cleared by "forget pinned key"."""
    os_family: str | None = None
    """Detected once via `uname -s` on the first successful poll (see COMMANDS_BY_OS), then reused -
    never re-detected on later polls."""
    auto_repin_host_key: bool = Field(
        default=True,
        description="A host presenting a different SSH key than the one pinned is re-pinned "
        "automatically instead of failing every poll - on by default, since a home LAN routinely "
        "reassigns an IP to a new machine (reimage, new VM). Turn off for strict pinning: a changed "
        "key then fails the poll until a human uses \"forget host key\".",
    )

    @field_validator("host", mode="before")
    @classmethod
    def _blank_host_is_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _host_and_device_together(self) -> "GenericSshConfig":
        if (self.host is None) != (self.device_id is None):
            raise ValueError("host and device_id must both be set, or both left unset for a wallet entry")
        return self


class SshCredential(BaseModel):
    username: str
    private_key: str | None = Field(default=None, description="Either this or password is required.")
    passphrase: str | None = Field(default=None, description="Only used if private_key is set.")
    password: str | None = None

    @model_validator(mode="after")
    def _key_or_password(self) -> "SshCredential":
        if not self.private_key and not self.password:
            raise ValueError("either private_key or password must be set")
        return self


def ssh_auth_kwargs(credential: dict[str, Any]) -> dict[str, Any]:
    """asyncssh.connect auth kwargs for a credential dict: a private key if present, otherwise a
    password - both are supported credential shapes for this plugin (see docs/credentials.md). Raises
    asyncssh.KeyImportError for a bad key, or KeyError if neither a private_key nor a password is set."""
    if credential.get("private_key"):
        key = asyncssh.import_private_key(
            credential["private_key"], passphrase=credential.get("passphrase")
        )
        return {"client_keys": [key]}
    return {"password": credential["password"], "client_keys": []}


def _detect_os_family(exit_status: int | None, raw: str) -> str:
    """Maps a `uname -s` attempt to a COMMANDS_BY_OS key.

    A nonzero exit (or no output) is the reliable signal for Windows: Win32-OpenSSH's default remote
    shell is cmd.exe, which has no `uname` builtin and fails the command - unlike a Unix-like shell,
    where a missing `uname` binary is rare enough not to special-case. An exit of 0 with unrecognized
    output (some other POSIX variant) falls back to "linux" with a logged warning - most Unix-like
    SSH-reachable devices (BusyBox systems, NAS appliances) answer most of its commands harmlessly even
    when a few paths don't exist."""
    name = raw.strip().lower()
    if exit_status == 0 and name == "linux":
        return "linux"
    if exit_status != 0 or not name:
        return "windows"
    logger.warning("generic_ssh_unrecognized_os", uname_s=raw.strip())
    return "linux"


class GenericSshPlugin:
    """Agentless SSH host health. Read-only by construction: every poll runs a fixed set of commands
    for the detected OS family (see commands.py), never a string built from config/credential input.
    Host keys are pinned on first use (see hostkey.py): the key learned on the first poll is stored in
    the integration's config and every later connection must present it.

    Linux is the only fully implemented command/parser family today (see commands.py); OS detection
    exists so a second family is a small, obvious addition later instead of a core change.
    """

    type_key: ClassVar[str] = "generic_ssh"
    display_name: ClassVar[str] = "Generic (SSH)"
    config_schema: ClassVar[type[BaseModel]] = GenericSshConfig
    credential_schema: ClassVar[type[BaseModel] | None] = SshCredential

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult:
        try:
            cfg = GenericSshConfig.model_validate(config)
        except ValueError as exc:
            return ValidationResult(ok=False, message=clean_validation_message(exc))
        if not credential or "username" not in credential:
            return ValidationResult(
                ok=False, message="An SSH credential (username + private key or password) is required"
            )
        if cfg.host is None:
            return ValidationResult(ok=True)  # a wallet entry: nothing to connect to yet
        if not await self.probe_credential(credential, cfg.host, cfg.port):
            return ValidationResult(
                ok=False,
                message=f"Could not connect or authenticate to {cfg.host}:{cfg.port} over SSH - "
                "check the host, port, username and private key/password.",
            )
        return ValidationResult(ok=True)

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]:
        cfg = GenericSshConfig.model_validate(config)
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

    async def probe_credential(self, credential: dict[str, Any], host: str, port: int = 22) -> bool:
        """Tries this credential against host:port with no prior trust - used only by the
        credential wallet (backend/app/discovery/auto_login.py), which gates this on the same
        host-key approval/pinning check `poll()` uses, so a secret is still never sent to a host
        whose key hasn't been trusted first."""
        has_secret = credential.get("private_key") or credential.get("password")
        if not credential.get("username") or not has_secret:
            return False
        try:
            scanned = await hostkey.scan_host_key(host, port, 5.0)
        except (asyncssh.Error, OSError, TimeoutError):
            return False
        line = hostkey.key_line(scanned)
        try:
            auth_kwargs = ssh_auth_kwargs(credential)
        except asyncssh.KeyImportError:
            return False
        connect_kwargs: dict[str, Any] = {
            "port": port,
            "username": credential["username"],
            "known_hosts": hostkey.known_hosts_for(host, port, line),
            "connect_timeout": 5.0,
            **auth_kwargs,
        }
        try:
            async with asyncssh.connect(host, **connect_kwargs):
                return True
        except (asyncssh.Error, OSError, TimeoutError):
            return False

    async def poll(
        self,
        config: dict[str, Any],
        credential: dict[str, Any] | None,
        target: TargetDescriptor,
    ) -> PollResult:
        cfg = GenericSshConfig.model_validate(config)
        if not credential:
            return PollResult(success=False, error_message="No credential configured")

        try:
            auth_kwargs = ssh_auth_kwargs(credential)
        except (KeyError, asyncssh.KeyImportError) as exc:
            return PollResult(success=False, error_message=f"Invalid SSH credential: {exc}")

        assert cfg.host is not None  # guaranteed: list_targets() never produces a target for a wallet entry

        outputs: dict[str, str] = {}
        learned: dict[str, Any] = {}
        os_family = cfg.os_family
        started = time.monotonic()
        try:
            pinned = cfg.host_key
            if not pinned:
                scanned = await hostkey.scan_host_key(cfg.host, cfg.port, cfg.timeout_seconds)
                pinned = hostkey.key_line(scanned)
                learned["host_key"] = pinned

            attempts = 2 if cfg.auto_repin_host_key else 1
            for attempt in range(attempts):
                try:
                    async with asyncssh.connect(
                        cfg.host,
                        port=cfg.port,
                        username=credential["username"],
                        known_hosts=hostkey.known_hosts_for(cfg.host, cfg.port, pinned),
                        connect_timeout=cfg.timeout_seconds,
                        **auth_kwargs,
                    ) as conn:
                        if not os_family:
                            detect_result = await conn.run(
                                DETECT_OS_COMMAND, check=False, timeout=cfg.timeout_seconds
                            )
                            os_family = _detect_os_family(
                                detect_result.exit_status, str(detect_result.stdout or "")
                            )
                            learned["os_family"] = os_family
                        commands = COMMANDS_BY_OS.get(os_family, LINUX_COMMANDS)
                        for key, command in commands.items():
                            result = await conn.run(command, check=False, timeout=cfg.timeout_seconds)
                            outputs[key] = str(result.stdout or "")
                    break
                except asyncssh.HostKeyNotVerifiable:
                    if attempt == attempts - 1:
                        raise
                    # On a LAN a changed key usually means this IP was reassigned to a different
                    # machine (reimage, new VM), not an attacker - re-pin the new key and retry once
                    # instead of failing every poll until a human clicks "forget host key".
                    scanned = await hostkey.scan_host_key(cfg.host, cfg.port, cfg.timeout_seconds)
                    pinned = hostkey.key_line(scanned)
                    learned["host_key"] = pinned
                    logger.warning("generic_ssh_host_key_changed", host=cfg.host, port=cfg.port)
        except asyncssh.HostKeyNotVerifiable:
            return PollResult(success=False, error_message=hostkey.changed_message(pinned or ""))
        except (asyncssh.Error, OSError, TimeoutError) as exc:
            return PollResult(success=False, error_message=str(exc))

        assert os_family is not None  # detected inside the loop above if cfg.os_family wasn't already set
        latency_ms = (time.monotonic() - started) * 1000

        parse_metrics = parsers.PARSERS_BY_OS.get(os_family, parsers.parse_linux_metrics)
        metrics = parse_metrics(outputs)

        return PollResult(
            success=True,
            latency_ms=latency_ms,
            metrics=metrics,
            hostname=outputs.get("hostname", "").strip() or None,
            learned_config=learned,
        )
