from pydantic import BaseModel

from app.api.schemas.alerts import AlertStateRead
from app.api.schemas.events import EventRead


class StatusCounts(BaseModel):
    up: int = 0
    down: int = 0
    degraded: int = 0
    unknown: int = 0


class HealthBucket(BaseModel):
    hour: str
    """Start of the hour (UTC), `YYYY-MM-DDTHH:00:00Z`."""
    devices: float | None
    services: float | None
    """Share of checks that succeeded in this hour (0 to 1); None when nothing was checked."""


class HealthTrend(BaseModel):
    buckets: list[HealthBucket]


class OverviewSummary(BaseModel):
    devices: StatusCounts
    services: StatusCounts
    integrations_ok: int
    integrations_error: int
    firing_alerts: list[AlertStateRead]
    recent_events: list[EventRead]
