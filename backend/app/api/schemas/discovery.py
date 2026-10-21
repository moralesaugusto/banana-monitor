import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.enums import CandidateStatus, CandidateType, DeviceType, ServiceType


class DiscoveredCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_type: CandidateType
    discovered_via: str
    network_id: int | None
    raw_attributes: dict[str, Any]
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    times_seen: int
    status: CandidateStatus
    resulting_device_id: int | None
    resulting_service_id: int | None


class AcceptDevicePayload(BaseModel):
    device_type: DeviceType
    display_name: str | None = None


class AcceptServicePayload(BaseModel):
    service_type: ServiceType
    name: str | None = None
    device_id: int | None = None
    config: dict[str, Any] = {}


class OuiStatusRead(BaseModel):
    entry_count: int
    updated_at: datetime.datetime | None
