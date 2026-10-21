import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import EntityType
from app.domain.metrics_models import MetricSample


async def get_latest_metric_values(
    session: AsyncSession, entity_type: EntityType, metric_name: str, entity_ids: list[int]
) -> dict[int, float]:
    """Latest value of `metric_name` per entity, without scanning full history."""
    if not entity_ids:
        return {}

    latest_ts_subq = (
        select(MetricSample.entity_id, func.max(MetricSample.ts).label("max_ts"))
        .where(
            MetricSample.entity_type == entity_type,
            MetricSample.metric_name == metric_name,
            MetricSample.entity_id.in_(entity_ids),
        )
        .group_by(MetricSample.entity_id)
        .subquery()
    )
    stmt = select(MetricSample.entity_id, MetricSample.value).join(
        latest_ts_subq,
        (MetricSample.entity_id == latest_ts_subq.c.entity_id)
        & (MetricSample.ts == latest_ts_subq.c.max_ts),
    )
    result = await session.execute(stmt)
    return {entity_id: value for entity_id, value in result.all()}


async def get_latest_metric_values_for_entity(
    session: AsyncSession, entity_type: EntityType, entity_id: int
) -> dict[str, float]:
    """Latest value of every metric recorded for one entity, keyed by metric name."""
    latest_ts_subq = (
        select(MetricSample.metric_name, func.max(MetricSample.ts).label("max_ts"))
        .where(MetricSample.entity_type == entity_type, MetricSample.entity_id == entity_id)
        .group_by(MetricSample.metric_name)
        .subquery()
    )
    stmt = select(MetricSample.metric_name, MetricSample.value).join(
        latest_ts_subq,
        (MetricSample.metric_name == latest_ts_subq.c.metric_name)
        & (MetricSample.ts == latest_ts_subq.c.max_ts),
    )
    result = await session.execute(stmt)
    return {name: value for name, value in result.all()}


async def get_recent_metric_samples(
    session: AsyncSession,
    entity_type: EntityType,
    entity_id: int,
    metric_name: str,
    limit: int = 100,
) -> list[tuple[datetime.datetime, float]]:
    stmt = (
        select(MetricSample.ts, MetricSample.value)
        .where(
            MetricSample.entity_type == entity_type,
            MetricSample.entity_id == entity_id,
            MetricSample.metric_name == metric_name,
        )
        .order_by(MetricSample.ts.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = [(ts, value) for ts, value in result.all()]
    rows.reverse()
    return rows
