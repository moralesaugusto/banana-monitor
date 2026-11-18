from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import get_databases
from app.domain.enums import EntityType
from app.domain.metrics_models import MetricSample, MetricsBase
from app.metrics import writer as writer_module
from app.metrics.writer import MetricsWriter


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.metrics_engine.begin() as conn:
        await conn.run_sync(MetricsBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


def _sample(writer: MetricsWriter, value: float) -> None:
    writer.enqueue_metric_sample(entity_type=EntityType.DEVICE, entity_id=1, metric_name="m", value=value)


async def _stored(databases) -> list[float]:
    async with databases.metrics_session_factory() as session:
        return list(await session.scalars(select(MetricSample.value).order_by(MetricSample.id)))


async def test_failed_flush_is_retried_in_order_ahead_of_newer_samples(databases) -> None:
    writer = MetricsWriter(databases)
    _sample(writer, 1)
    _sample(writer, 2)

    real_factory = databases.metrics_session_factory
    databases.metrics_session_factory = _broken  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        await writer._flush()
    databases.metrics_session_factory = real_factory

    _sample(writer, 3)
    await writer._flush()

    assert await _stored(databases) == [1, 2, 3]
    assert writer.dropped == 0


async def test_overflowing_backlog_drops_the_oldest_and_counts_them(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(writer_module, "MAX_BACKLOG", 3)
    writer = MetricsWriter(databases)
    for value in range(1, 6):
        _sample(writer, value)

    real_factory = databases.metrics_session_factory
    databases.metrics_session_factory = _broken  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        await writer._flush()
    databases.metrics_session_factory = real_factory

    assert writer.dropped == 2
    await writer._flush()
    assert await _stored(databases) == [3, 4, 5]


def _broken(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("database is locked")
