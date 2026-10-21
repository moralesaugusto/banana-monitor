import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from app.logging_setup import get_logger

logger = get_logger(__name__)


class PeriodicTask:
    """Runs an async callable on a fixed interval, forever, until stopped.

    A single failing run is logged and never kills the loop - the next
    interval just tries again.
    """

    def __init__(self, name: str, interval_seconds: float, func: Callable[[], Awaitable[None]]) -> None:
        self._name = name
        self._interval = interval_seconds
        self._func = func
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            try:
                await self._func()
            except Exception:
                logger.warning("periodic_task_failed", name=self._name, exc_info=True)
            await asyncio.sleep(self._interval)
