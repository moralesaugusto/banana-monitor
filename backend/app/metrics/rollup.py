import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult

from app.db.session import Databases
from app.domain.enums import EntityType
from app.domain.metrics_models import CheckResult, Granularity, MetricRollup, MetricSample
from app.logging_setup import get_logger

logger = get_logger(__name__)

ROLLUP_INTERVAL_SECONDS = 300.0
RAW_RETENTION = datetime.timedelta(hours=24)
ROLLUP_RETENTION = datetime.timedelta(days=90)
BUCKET_SECONDS = 300


def _floor_to_bucket(ts: datetime.datetime, bucket_seconds: int) -> datetime.datetime:
    epoch = ts.timestamp()
    floored = epoch - (epoch % bucket_seconds)
    return datetime.datetime.fromtimestamp(floored, tz=datetime.UTC)


async def run_rollup_and_retention(databases: Databases) -> None:
    now = datetime.datetime.now(datetime.UTC)
    raw_cutoff = now - RAW_RETENTION

    async with databases.metrics_session_factory() as session:
        result = await session.execute(select(MetricSample).where(MetricSample.ts < raw_cutoff))
        stale_samples = list(result.scalars().all())

        if stale_samples:
            buckets: dict[tuple[EntityType, int, str, datetime.datetime], list[float]] = {}
            for sample in stale_samples:
                bucket_start = _floor_to_bucket(sample.ts, BUCKET_SECONDS)
                key = (sample.entity_type, sample.entity_id, sample.metric_name, bucket_start)
                buckets.setdefault(key, []).append(sample.value)

            for (entity_type, entity_id, metric_name, bucket_start), values in buckets.items():
                existing = await session.execute(
                    select(MetricRollup).where(
                        MetricRollup.entity_type == entity_type,
                        MetricRollup.entity_id == entity_id,
                        MetricRollup.metric_name == metric_name,
                        MetricRollup.granularity == Granularity.FIVE_MINUTE,
                        MetricRollup.bucket_start == bucket_start,
                    )
                )
                row = existing.scalar_one_or_none()
                if row is None:
                    session.add(
                        MetricRollup(
                            entity_type=entity_type,
                            entity_id=entity_id,
                            metric_name=metric_name,
                            bucket_start=bucket_start,
                            granularity=Granularity.FIVE_MINUTE,
                            avg_value=sum(values) / len(values),
                            min_value=min(values),
                            max_value=max(values),
                            sample_count=len(values),
                        )
                    )
                else:
                    total = row.avg_value * row.sample_count + sum(values)
                    row.sample_count += len(values)
                    row.avg_value = total / row.sample_count
                    row.min_value = min(row.min_value, min(values))
                    row.max_value = max(row.max_value, max(values))

            await session.execute(delete(MetricSample).where(MetricSample.ts < raw_cutoff))
            await session.commit()
            logger.info(
                "metrics_rolled_up", samples=len(stale_samples), buckets=len(buckets)
            )

        await session.execute(delete(CheckResult).where(CheckResult.ts < raw_cutoff))
        await session.commit()

        rollup_cutoff = now - ROLLUP_RETENTION
        delete_result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
            delete(MetricRollup).where(MetricRollup.bucket_start < rollup_cutoff)
        )
        await session.commit()
        if delete_result.rowcount:
            logger.info("old_rollups_pruned", count=delete_result.rowcount)


TRIM_FRACTION = 0.2


async def enforce_size_limit(databases: Databases, db_path: Path, max_bytes: int) -> None:
    """Deletes the oldest raw rows (then the oldest rollups) until the file is
    under the cap. Freed pages are only returned to the OS by VACUUM, so run it
    after trimming. Never touches the app or credentials databases."""
    if not db_path.exists() or db_path.stat().st_size <= max_bytes:
        return
    async with databases.metrics_session_factory() as session:
        for model, column in ((CheckResult, CheckResult.ts), (MetricSample, MetricSample.ts),
                              (MetricRollup, MetricRollup.bucket_start)):
            total = await session.scalar(select(func.count()).select_from(model)) or 0
            if total == 0:
                continue
            cutoff = await session.scalar(
                select(column).order_by(column).offset(int(total * TRIM_FRACTION)).limit(1)
            )
            if cutoff is not None:
                await session.execute(delete(model).where(column <= cutoff))
        await session.commit()
    async with databases.metrics_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("VACUUM")
    logger.warning("metrics_db_trimmed", max_mb=max_bytes // (1024 * 1024))
