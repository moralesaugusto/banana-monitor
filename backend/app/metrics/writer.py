import asyncio
import contextlib
from collections import deque
from functools import lru_cache
from typing import Any

from app.db.session import Databases, get_databases
from app.domain.metrics_models import CheckResult, MetricSample
from app.logging_setup import get_logger

FLUSH_INTERVAL_SECONDS = 2.0
MAX_BACKLOG = 50_000

logger = get_logger(__name__)


class MetricsWriter:
    """Batches high-frequency metric writes into periodic transactions.

    Individual TargetRunners enqueue results instead of writing metrics.db
    directly, so many concurrent pollers never contend for SQLite write locks.
    """

    def __init__(self, databases: Databases, flush_interval: float = FLUSH_INTERVAL_SECONDS) -> None:
        self._databases = databases
        self._flush_interval = flush_interval
        self._queue: deque[tuple[str, dict[str, Any]]] = deque()
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0
        """Records discarded because the backlog outgrew MAX_BACKLOG during a metrics-database outage."""

    def enqueue_check_result(self, **kwargs: Any) -> None:
        self._queue.append(("check_result", kwargs))

    def enqueue_metric_sample(self, **kwargs: Any) -> None:
        self._queue.append(("metric_sample", kwargs))

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._flush()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            try:
                await self._flush()
            except Exception as exc:  # noqa: BLE001 - a locked or briefly unavailable database must not end the writer
                logger.warning(
                    "metrics_flush_failed",
                    error=repr(exc),
                    queued=len(self._queue),
                    dropped_total=self.dropped,
                )

    async def _flush(self) -> None:
        if not self._queue:
            return
        items = list(self._queue)
        self._queue.clear()

        try:
            async with self._databases.metrics_session_factory() as session:
                for kind, payload in items:
                    if kind == "check_result":
                        session.add(CheckResult(**payload))
                    else:
                        session.add(MetricSample(**payload))
                await session.commit()
        except Exception:
            # Put the batch back ahead of anything queued meanwhile so the next flush retries it in order.
            # Memory stays bounded: past MAX_BACKLOG the oldest records go, counted and logged.
            self._queue.extendleft(reversed(items))
            overflow = len(self._queue) - MAX_BACKLOG
            if overflow > 0:
                for _ in range(overflow):
                    self._queue.popleft()
                self.dropped += overflow
                logger.error("metrics_backlog_dropped", dropped=overflow, dropped_total=self.dropped)
            raise


@lru_cache
def get_metrics_writer() -> MetricsWriter:
    return MetricsWriter(get_databases())
