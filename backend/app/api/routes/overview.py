import datetime

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import AppSession, MetricsSession
from app.api.schemas.alerts import AlertStateRead
from app.api.schemas.events import EventRead
from app.api.schemas.overview import HealthBucket, HealthTrend, OverviewSummary, StatusCounts
from app.domain.enums import AlertState, EntityType, IntegrationStatus
from app.domain.metrics_models import CheckResult
from app.domain.models import AlertStateRow, Device, Event, Integration, Service, utcnow

router = APIRouter(prefix="/overview", tags=["overview"])

TREND_HOURS = 24


@router.get("/health-trend", response_model=HealthTrend)
async def get_health_trend(session: MetricsSession) -> HealthTrend:
    """Per hour over the last day: the share of device and service checks that succeeded."""
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - datetime.timedelta(hours=TREND_HOURS - 1)
    hour = func.strftime("%Y-%m-%dT%H", CheckResult.ts)
    rows = await session.execute(
        select(hour, CheckResult.entity_type, func.avg(CheckResult.success))
        .where(CheckResult.ts >= start, CheckResult.entity_type.in_([EntityType.DEVICE, EntityType.SERVICE]))
        .group_by(hour, CheckResult.entity_type)
    )
    ratios: dict[tuple[str, EntityType], float] = {(h, kind): float(avg) for h, kind, avg in rows.all()}
    buckets = []
    for offset in range(TREND_HOURS):
        moment = start + datetime.timedelta(hours=offset)
        key = moment.strftime("%Y-%m-%dT%H")
        buckets.append(
            HealthBucket(
                hour=f"{key}:00:00Z",
                devices=ratios.get((key, EntityType.DEVICE)),
                services=ratios.get((key, EntityType.SERVICE)),
            )
        )
    return HealthTrend(buckets=buckets)


async def _status_counts(session: AppSession, model: type[Device] | type[Service]) -> StatusCounts:
    result = await session.execute(select(model.status, func.count()).group_by(model.status))
    counts = StatusCounts()
    for status, count in result.all():
        setattr(counts, status.value, count)
    return counts


@router.get("", response_model=OverviewSummary)
async def get_overview(session: AppSession) -> OverviewSummary:
    devices = await _status_counts(session, Device)
    services = await _status_counts(session, Service)

    integration_result = await session.execute(
        select(Integration.status, func.count()).group_by(Integration.status)
    )
    integration_counts: dict[IntegrationStatus, int] = {
        status: count for status, count in integration_result.all()
    }

    firing_result = await session.execute(
        select(AlertStateRow)
        .where(AlertStateRow.state.in_([AlertState.FIRING, AlertState.FLAPPING]))
        .order_by(AlertStateRow.state_changed_at.desc())
        .limit(20)
    )
    events_result = await session.execute(select(Event).order_by(Event.ts.desc()).limit(10))

    return OverviewSummary(
        devices=devices,
        services=services,
        integrations_ok=integration_counts.get(IntegrationStatus.OK, 0),
        integrations_error=integration_counts.get(IntegrationStatus.ERROR, 0),
        firing_alerts=[AlertStateRead.model_validate(a) for a in firing_result.scalars().all()],
        recent_events=[EventRead.model_validate(e) for e in events_result.scalars().all()],
    )
