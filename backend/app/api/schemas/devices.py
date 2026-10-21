import datetime
import ipaddress
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, computed_field

from app.discovery.reachability import device_is_inactive
from app.domain.enums import DeviceType, HealthStatus, ServiceType


class DeviceAddressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ip_address: str
    mac_address: str | None
    is_primary: bool
    vendor: str | None = None
    """Best-effort IEEE OUI lookup on `mac_address`, filled in by the route
    handler (not a stored column) - see `app.discovery.oui`."""


class DeviceServiceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    service_type: ServiceType
    status: HealthStatus


def _check_ip(value: object) -> object:
    if value is None or value == "":
        return None
    ipaddress.ip_address(str(value).strip())
    return str(value).strip()


IpAddress = Annotated[str | None, BeforeValidator(_check_ip)]


class DeviceBase(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    hostname: str | None = None
    primary_ip: IpAddress = None
    device_type: DeviceType
    network_id: int | None = None
    tags: list[str] = []
    notes: str | None = None


class DeviceCreate(DeviceBase):
    site_id: int | None = None


class DeviceUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    hostname: str | None = None
    primary_ip: IpAddress = None
    device_type: DeviceType | None = None
    network_id: int | None = None
    tags: list[str] | None = None
    notes: str | None = None
    managed: bool | None = None


class DeviceRead(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    status: HealthStatus
    managed: bool
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def inactive(self) -> bool:
        """Down and unseen for longer than reachability.INACTIVE_AFTER - old and gone, not just a
        momentary blip. AI Mode's automatic target selection skips inactive devices."""
        return device_is_inactive(self.status, self.last_seen_at)


class DeviceListRead(DeviceRead):
    role: str = "Unclassified"
    vendor: str | None = None
    network_name: str | None = None
    service_count: int = 0
    services_up: int = 0


class DeviceDetail(DeviceRead):
    addresses: list[DeviceAddressRead] = []
    services: list[DeviceServiceSummary] = []
    metrics: dict[str, float] = {}


class MetricPoint(BaseModel):
    ts: datetime.datetime
    value: float
