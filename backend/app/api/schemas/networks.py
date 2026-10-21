import datetime
import ipaddress
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.domain.enums import HealthStatus


def _check_cidr(value: object) -> object:
    return str(ipaddress.ip_network(str(value).strip(), strict=False))


Cidr = Annotated[str, BeforeValidator(_check_cidr)]


class NetworkBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    cidr: Cidr
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    description: str | None = None


class NetworkCreate(NetworkBase):
    site_id: int | None = None


class NetworkUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    cidr: Cidr | None = None
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    description: str | None = None


class NetworkRead(NetworkBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int


class ScanStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    network_id: int
    status: str
    total_hosts: int
    scanned_hosts: int
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None
    failed_hosts: int = 0
    error: str | None = None


class NetworkCredentialBindingCreate(BaseModel):
    credential_id: int
    priority: int = 0


class NetworkCredentialBindingRead(BaseModel):
    """Deliberately excludes any secret material - credential_id is just an
    opaque reference into credentials.db, same as Integration.credential_id."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    network_id: int
    credential_id: int
    priority: int
    created_at: datetime.datetime


class AddressCell(BaseModel):
    """One IP in a network's address space, for the network-map grid - see
    docs/decisions.md's address-count cap rationale."""

    ip: str
    status: HealthStatus | None = None
    """None means no Device/DeviceAddress is recorded at this IP at all (free)."""
    device_id: int | None = None
    display_name: str | None = None
    managed: bool | None = None


class NetworkMap(BaseModel):
    network_id: int
    cidr: str
    total_addresses: int
    truncated: bool
    """True when total_addresses exceeds the per-address rendering cap and
    `addresses` is empty - `summary` is populated instead."""
    addresses: list[AddressCell] = []
    summary: dict[str, int] | None = None
    """Counts by status, used only when `truncated` is true."""
