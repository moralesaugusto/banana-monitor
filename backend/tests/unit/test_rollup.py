import datetime

import pytest

from app.credentials.models import CredentialsBase
from app.db.session import get_databases
from app.domain.enums import EntityType
from app.domain.metrics_models import CheckResult, MetricRollup, MetricSample, MetricsBase
from app.domain.models import Base as AppBase
from app.metrics.rollup import RAW_RETENTION, ROLLUP_RETENTION, run_rollup_and_retention


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with dbs.metrics_engine.begin() as conn:
        await conn.run_sync(MetricsBase.metadata.create_all)
    async with dbs.credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


@pytest.mark.asyncio
async def test_stale_samples_rolled_up_and_pruned(databases) -> None:
    now = datetime.datetime.now(datetime.UTC)
    old_ts = now - RAW_RETENTION - datetime.timedelta(hours=1)
    recent_ts = now - datetime.timedelta(minutes=1)

    def sample(value: float, ts: datetime.datetime) -> MetricSample:
        return MetricSample(
            entity_type=EntityType.DEVICE, entity_id=1, metric_name="cpu_percent", value=value, ts=ts
        )

    def check(ts: datetime.datetime) -> CheckResult:
        return CheckResult(entity_type=EntityType.DEVICE, entity_id=1, success=True, ts=ts)

    async with databases.metrics_session_factory() as session:
        session.add(sample(10.0, old_ts))
        session.add(sample(20.0, old_ts))
        session.add(sample(99.0, recent_ts))
        session.add(check(old_ts))
        session.add(check(recent_ts))
        await session.commit()

    await run_rollup_and_retention(databases)

    async with databases.metrics_session_factory() as session:
        from sqlalchemy import select

        samples = (await session.execute(select(MetricSample))).scalars().all()
        assert len(samples) == 1
        assert samples[0].value == 99.0

        check_results = (await session.execute(select(CheckResult))).scalars().all()
        assert len(check_results) == 1
        assert check_results[0].ts == recent_ts

        rollups = (await session.execute(select(MetricRollup))).scalars().all()
        assert len(rollups) == 1
        assert rollups[0].sample_count == 2
        assert rollups[0].avg_value == 15.0
        assert rollups[0].min_value == 10.0
        assert rollups[0].max_value == 20.0


@pytest.mark.asyncio
async def test_old_rollups_pruned(databases) -> None:
    now = datetime.datetime.now(datetime.UTC)
    async with databases.metrics_session_factory() as session:
        session.add(
            MetricRollup(
                entity_type=EntityType.DEVICE, entity_id=1, metric_name="cpu_percent",
                bucket_start=now - ROLLUP_RETENTION - datetime.timedelta(days=1),
                granularity="5m", avg_value=1.0, min_value=1.0, max_value=1.0, sample_count=1,
            )
        )
        session.add(
            MetricRollup(
                entity_type=EntityType.DEVICE, entity_id=1, metric_name="cpu_percent",
                bucket_start=now - datetime.timedelta(days=1),
                granularity="5m", avg_value=1.0, min_value=1.0, max_value=1.0, sample_count=1,
            )
        )
        await session.commit()

    await run_rollup_and_retention(databases)

    async with databases.metrics_session_factory() as session:
        from sqlalchemy import select

        rollups = (await session.execute(select(MetricRollup))).scalars().all()
        assert len(rollups) == 1


async def test_enforce_size_limit_is_noop_under_cap(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from app.db.session import get_databases
    from app.metrics.rollup import enforce_size_limit

    db_file = tmp_path / "small.db"
    db_file.write_bytes(b"x" * 10)
    await enforce_size_limit(get_databases(), db_file, 1024)
    assert db_file.read_bytes() == b"x" * 10
