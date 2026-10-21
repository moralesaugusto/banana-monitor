from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ValidationError


class ValidationResult(BaseModel):
    ok: bool
    message: str | None = None


class TargetDescriptor(BaseModel):
    external_ref: str
    display_name: str
    attributes: dict[str, Any] = {}
    device_id: int | None = None
    """Set by plugins that already know the exact Device (e.g. generic_ssh, whose
    config names a pre-existing device). Left None for plugins that enumerate
    their own targets (e.g. proxmox), so the scheduler auto-provisions and
    tracks the Device via an IntegrationTarget keyed by external_ref."""


class DiscoveredItem(BaseModel):
    candidate_type: str
    external_ref: str
    attributes: dict[str, Any] = {}


class PollResult(BaseModel):
    success: bool
    latency_ms: float | None = None
    error_message: str | None = None
    metrics: dict[str, float] = {}
    hostname: str | None = None
    """The name the device reports for itself; the scheduler offers it as the device's host name."""
    learned_config: dict[str, Any] = {}
    """Config values the plugin learned while polling (an SSH host key pinned on first use). The scheduler
    stores them in the integration's config; the plugin itself never writes anywhere."""


class IntegrationPlugin(Protocol):
    """Contract every integration (present and future) implements.

    Plugins are pure functions of (config, credential, network I/O) -> structured
    results. Only the scheduler persists results to the database - plugins never
    touch the DB directly, which keeps them independently testable.
    """

    type_key: ClassVar[str]
    display_name: ClassVar[str]
    config_schema: ClassVar[type[BaseModel]]
    credential_schema: ClassVar[type[BaseModel] | None]

    async def validate_config(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> ValidationResult: ...

    async def list_targets(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[TargetDescriptor]: ...

    async def discover(
        self, config: dict[str, Any], credential: dict[str, Any] | None
    ) -> list[DiscoveredItem]: ...

    async def poll(
        self,
        config: dict[str, Any],
        credential: dict[str, Any] | None,
        target: TargetDescriptor,
    ) -> PollResult: ...

    # Not part of this Protocol (so http_tcp/dns/dhcp/virustotal, which have no host to probe or no
    # credential at all, don't need a meaningless implementation): a plugin whose config accepts a
    # `host` may implement
    #
    #   async def probe_credential(self, credential: dict[str, Any], host: str, port: int = ...) -> bool
    #
    # to support the credential wallet (backend/app/discovery/auto_login.py) - a credential saved with
    # no host, tried against any host discovery finds that looks like this plugin's kind of service.
    # generic_ssh, proxmox, adguard_home, homebridge, omada and windows_winrm implement it today.


def clean_validation_message(exc: ValueError) -> str:
    """Every plugin's validate_config() catches ValueError from `<Config>.model_validate(config)` and
    returns str(exc) as the user-facing ValidationResult.message. For a pydantic ValidationError that's a
    multi-line dump ("1 validation error for ProxmoxConfig\\nhost\\n  Value error, ... [type=value_error, ...]
    \\n    For further information visit https://errors.pydantic.dev/...") - useful in a traceback, not in a
    form's error banner. This keeps just each error's own message, semicolon-joined for the (rare) case of
    more than one."""
    if isinstance(exc, ValidationError):
        messages = [
            msg.removeprefix("Value error, ")  # pydantic's own prefix for a custom validator's message
            for error in exc.errors()
            if (msg := error["msg"])
        ]
        if messages:
            return "; ".join(messages)
    return str(exc)
