"""One place that owns fire-and-forget tasks started from request handlers.

A bare `asyncio.create_task(...)` whose result is dropped can be garbage-collected mid-run
(the event loop holds only a weak reference) and its exception is never reported. Tasks started
here are kept alive, log any failure, and are cancelled on shutdown.
"""

import asyncio
import contextlib
import weakref
from collections.abc import Coroutine
from typing import Any

from app.logging_setup import get_logger

logger = get_logger(__name__)

_tasks: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_done)
    return task


def _done(task: asyncio.Task[Any]) -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("background_task_failed", task=task.get_name(), error=repr(exc), exc_info=exc)


async def cancel_all() -> None:
    """Called at shutdown, before the databases are disposed."""
    pending = list(_tasks)
    for task in pending:
        task.cancel()
    with contextlib.suppress(Exception):
        await asyncio.gather(*pending, return_exceptions=True)


_loop_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)


def named_lock(name: str) -> asyncio.Lock:
    """A process-wide lock per name for the running event loop (an asyncio.Lock must not be shared
    between loops, which matters for tests that each start their own)."""
    locks = _loop_locks.setdefault(asyncio.get_running_loop(), {})
    return locks.setdefault(name, asyncio.Lock())
