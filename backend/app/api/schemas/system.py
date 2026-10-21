from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DiscoverySettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nmap_enabled: bool
    scan_mode: Literal["manual", "auto"]
    auto_interval_seconds: int
    timing_template: int
    host_timeout_seconds: int
    max_retries: int
    version_intensity: int
    ai_mode_enabled: bool
    max_db_size_mb: int
    ssh_hostkey_approval: bool
    ssh_hostkey_auto_repin: bool
    auto_accept_services: bool
    dns_server: str


class DiscoverySettingsUpdate(BaseModel):
    nmap_enabled: bool | None = None
    scan_mode: Literal["manual", "auto"] | None = None
    auto_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    timing_template: int | None = Field(default=None, ge=0, le=5)
    host_timeout_seconds: int | None = Field(default=None, ge=5, le=300)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    version_intensity: int | None = Field(default=None, ge=0, le=9)
    ai_mode_enabled: bool | None = None
    max_db_size_mb: int | None = Field(default=None, ge=16, le=102400)
    ssh_hostkey_approval: bool | None = None
    ssh_hostkey_auto_repin: bool | None = None
    auto_accept_services: bool | None = None
    dns_server: str | None = Field(default=None, max_length=253, pattern=r"^[A-Za-z0-9.:_-]*$")


class InternetAccess(BaseModel):
    blocked: bool
    agents: list[str]
    """Enabled agents that have a web tool ticked."""


class InternetAccessUpdate(BaseModel):
    blocked: bool


class ScanOverview(BaseModel):
    scanning: bool
    total_hosts: int
    scanned_hosts: int
