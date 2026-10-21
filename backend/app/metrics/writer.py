import asyncio
import contextlib
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
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def enqueue_check_result(self, **kwargs: Any) -> None:
        self._queue.put_nowait(("check_result", kwargs))

    def enqueue_metric_sample(self, **kwargs: Any) -> None:
        self._queue.put_nowait(("metric_sample", kwargs))

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
                logger.warning("metrics_flush_failed", error=repr(exc), queued=self._queue.qsize())

    async def _flush(self) -> None:
        items: list[tuple[str, dict[str, Any]]] = []
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
        if not items:
            return

        try:
            async with self._databases.metrics_session_factory() as session:
                for kind, payload in items:
                    if kind == "check_result":
                        session.add(CheckResult(**payload))
                    else:
                        session.add(MetricSample(**payload))
                await session.commit()
        except Exception:
            # Put the batch back (oldest first) so the next flush retries it; bounded so a long outage
            # cannot grow memory without limit.
            for item in items[-MAX_BACKLOG:]:
                self._queue.put_nowait(item)
            raise


@lru_cache
def get_metrics_writer() -> MetricsWriter:
    return MetricsWriter(get_databases())
