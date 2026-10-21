import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import HealthStatus, ServiceType


class ServiceBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    service_type: ServiceType
    device_id: int | None = None
    config: dict[str, Any] = {}


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    service_type: ServiceType | None = None
    device_id: int | None = None
    config: dict[str, Any] | None = None
    managed: bool | None = None


class ServiceRead(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: HealthStatus
    managed: bool
    last_checked_at: datetime.datetime | None
    port: int | None = None
    source: str = "manual"
    fingerprint: dict[str, Any] | None = None
    last_latency_ms: float | None = None
    device_vendor: str | None = None
    """Best-effort IEEE OUI lookup on the parent device's MAC, filled in by
    the route handler (not a stored column) - see `app.discovery.oui`."""


class ServiceBulkAction(BaseModel):
    ids: list[int]
    action: Literal["delete", "monitor", "unmonitor"]
