"""Starts AI Mode runs on a timer, so discovery keeps going without anyone clicking - the mechanism
behind "always running" continuous mode when the interval is set low, as well as an occasional sweep
when set high.

Every tick (`SCHEDULE_TICK_SECONDS`) this checks whether a scheduled run is due: the schedule is on,
AI Mode is enabled, the interval has passed since the last scheduled run finished, and no run is active. Each
scheduled run covers the next batch of devices after the last one it handled (wrapping around), so over
several runs every device still assigned to a configured network gets visited even when there are more
devices than `max_targets`. Runs stop
themselves at the time limit (`max_run_minutes`), whether scheduled or started by hand - that cap, plus
`max_targets` and the schema's floor on how low the interval can go, are what keep a tight loop from
running away with LLM calls or host load.
"""

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.background import named_lock
from app.db.session import Databases
from app.discovery.reachability import INACTIVE_AFTER
from app.domain.bootstrap import ensure_default_ai_mode_settings, ensure_default_discovery_settings
from app.domain.enums import DeviceType, HealthStatus
from app.domain.models import AiRun, Device, Network, utcnow
from app.llm.agent import create_run, reap_orphaned_runs, running_run_id
from app.llm.orchestrator import spawn_run
from app.logging_setup import get_logger

logger = get_logger(__name__)

SCHEDULE_TICK_SECONDS = 5.0
RUN_START_LOCK = "ai-run-start"  # shared with the API's start endpoint (routes/ai_mode.py)


def next_run_at(
    enabled: bool, last: datetime.datetime | None, interval_seconds: int
) -> datetime.datetime | None:
    """When the next scheduled run becomes due; None when the schedule is off."""
    if not enabled:
        return None
    return utcnow() if last is None else last + datetime.timedelta(seconds=interval_seconds)


async def loop_anchor(
    session: AsyncSession, last_started: datetime.datetime | None
) -> datetime.datetime | None:
    """What the interval counts from: when the last scheduled run finished (or started, if it has not
    finished), so a slow run never eats into the pause and runs can never queue up back to back."""
    finished = await session.scalar(
        select(AiRun.finished_at)
        .where(AiRun.started_by == "schedule", AiRun.finished_at.is_not(None))
        .order_by(AiRun.id.desc())
        .limit(1)
    )
    return max(filter(None, (last_started, finished)), default=None)


async def next_targets(databases: Databases, cursor: int, limit: int) -> tuple[list[str], int]:
    """The next `limit` device IPs after `cursor` by device id, wrapping around to the start.
    Only devices that currently belong to a configured network are eligible - a device whose
    network was deleted becomes unassigned (network_id None, see networks.py's delete_network)
    rather than being removed itself, and should drop out of automatic scanning along with it
    instead of being targeted forever. A device that was never assigned a network in the first
    place is excluded the same way; target it explicitly (payload.targets, or a direct message to
    an agent) if you want AI Mode to look at it anyway. An inactive device (down and unseen for
    longer than reachability.INACTIVE_AFTER - see device_is_inactive) is excluded too: nothing
    keeps trying to discover, inspect or act on a host nothing has found in days."""
    cutoff = utcnow() - INACTIVE_AFTER
    async with databases.app_session_factory() as session:
        rows = (
            await session.execute(
                select(Device.id, Device.primary_ip)
                .where(
                    Device.primary_ip.is_not(None),
                    Device.network_id.is_not(None),
                    Device.device_type != DeviceType.PLATFORM_SELF,
                    (Device.status != HealthStatus.DOWN)
                    | (Device.last_seen_at.is_not(None) & (Device.last_seen_at > cutoff)),
                )
                .order_by(Device.id)
            )
        ).all()
    if not rows:
        return [], cursor
    after = [r for r in rows if r.id > cursor]
    batch = (after + [r for r in rows if r.id <= cursor])[:limit]
    return [r.primary_ip for r in batch], batch[-1].id


async def _has_network(databases: Databases) -> bool:
    async with databases.app_session_factory() as session:
        return await session.scalar(select(Network.id).limit(1)) is not None


async def run_ai_schedule(databases: Databases) -> None:
    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        ai_enabled = (await ensure_default_discovery_settings(session)).ai_mode_enabled
        due = next_run_at(
            settings.schedule_enabled,
            await loop_anchor(session, settings.last_scheduled_at),
            settings.schedule_interval_seconds,
        )
        if not ai_enabled or due is None or utcnow() < due:
            return
        entry, cursor, limit = settings.schedule_entry_agent, settings.schedule_cursor, settings.max_targets

    async with named_lock(RUN_START_LOCK):  # same lock as a manual start: one run at a time
        await reap_orphaned_runs(databases)
        if await running_run_id(databases) is not None:
            return  # still busy: try again next tick, the run that is active is not interrupted
        targets, new_cursor = await next_targets(databases, cursor, limit)
        if not targets and not await _has_network(databases):
            return
        try:
            run_id = await create_run(databases, targets, False, entry, None, started_by="schedule")
        except ValueError as exc:
            logger.warning("ai_schedule_skipped", error=str(exc))
            return

        async with databases.app_session_factory() as session:
            settings = await ensure_default_ai_mode_settings(session)
            settings.last_scheduled_at = utcnow()
            settings.schedule_cursor = new_cursor
            await session.commit()
        logger.info("ai_scheduled_run_started", run_id=run_id, targets=len(targets))
        spawn_run(databases, run_id)
