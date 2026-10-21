"""AI Mode run bookkeeping shared by the orchestrator: default prompt, run
creation (which snapshots every agent), orphan reaping and the step recorder.
The multi-agent loop itself lives in `app.llm.orchestrator`.
"""

import asyncio
import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Databases
from app.domain.bootstrap import (
    ensure_default_agents,
    ensure_default_ai_mode_settings,
)
from app.domain.models import AiAgent, AiRun, AiRunStep, Device, Network, utcnow
from app.llm.provider import effective_endpoint
from app.logging_setup import get_logger

logger = get_logger(__name__)

MAX_STORED_CONTENT_CHARS = 3000

DEFAULT_SYSTEM_PROMPT = (
    "Find open ports on each given target IP: run_nmap -Pn -sT -T4 --open (no -sV), then "
    "report_open_ports once per target. Don't guess services or call record_service - reviewer "
    "does that. Stick to given targets, unless asked to find new ones: then discover_hosts with a "
    "CIDR (e.g. 192.168.1.0/24), never a single IP. Scan everything, then report everything. End "
    "with a one-paragraph summary."
)


def _clip(value: Any) -> Any:
    """Keeps stored traces bounded: long strings are truncated, structure is kept."""
    if isinstance(value, str):
        if len(value) <= MAX_STORED_CONTENT_CHARS:
            return value
        return value[:MAX_STORED_CONTENT_CHARS] + "...[clipped]"
    if isinstance(value, list):
        return [_clip(v) for v in value]
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    return value


async def network_scope(session: AsyncSession) -> list[dict[str, Any]]:
    """Every configured network with its device count, so the entry agent sees the whole scope and not
    only the networks that already have devices."""
    rows = await session.execute(
        select(Network.name, Network.cidr, func.count(Device.id))
        .outerjoin(Device, Device.network_id == Network.id)
        .group_by(Network.id)
        .order_by(Network.id)
    )
    return [{"name": name, "cidr": cidr, "devices": count} for name, cidr, count in rows]


async def create_run(
    databases: Databases,
    targets: list[str],
    dry_run: bool,
    entry_agent: str = "discoverer",
    message: str | None = None,
    started_by: str = "manual",
) -> int:
    """Snapshots every enabled agent's effective config, so a trace remains
    explainable after the agents are edited. Returns the new run id."""
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        ai_settings = await ensure_default_ai_mode_settings(session)
        agents = list(await session.scalars(select(AiAgent).where(AiAgent.enabled).order_by(AiAgent.id)))
        networks = await network_scope(session)
        entry = next((a for a in agents if a.name == entry_agent), None)
        if entry is None:
            raise ValueError(f"entry agent {entry_agent!r} does not exist or is disabled")
        endpoints = {
            a.name: effective_endpoint(
                ai_settings,
                provider=a.provider,
                base_url=a.base_url,
                model=a.model_override,
                credential_id=a.credential_id,
            )
            for a in agents
        }
        entry_endpoint = endpoints[entry.name]
        run = AiRun(
            targets=targets,
            dry_run=dry_run,
            started_by=started_by,
            model=entry_endpoint.model,
            base_url=entry_endpoint.base_url,
            system_prompt=entry.system_prompt or DEFAULT_SYSTEM_PROMPT,
            settings_snapshot={
                "max_iterations": entry.max_iterations,
                "temperature": entry.temperature,
                "enabled_tools": list(entry.enabled_tools),
                "entry_agent": entry.name,
                "max_run_seconds": (
                    max([ai_settings.max_run_minutes, *(a.max_run_minutes for a in agents)]) * 60
                ),
                "default_max_run_minutes": ai_settings.max_run_minutes,
                "llm_timeout_seconds": ai_settings.llm_call_timeout_seconds,
                "ollama_max_concurrent_calls": ai_settings.ollama_max_concurrent_calls,
                "openrouter_max_concurrent_calls": ai_settings.openrouter_max_concurrent_calls,
                "message": message,
                "networks": networks,
                "default_model": ai_settings.llm_model,
                "agents": [
                    {
                        "name": a.name,
                        "role": a.role,
                        "system_prompt": a.system_prompt or DEFAULT_SYSTEM_PROMPT,
                        "provider": endpoints[a.name].provider.value,
                        "base_url": endpoints[a.name].base_url,
                        "model": endpoints[a.name].model,
                        "credential_id": endpoints[a.name].credential_id,  # a reference, never the key
                        "temperature": a.temperature,
                        "max_iterations": a.max_iterations,
                        "enabled_tools": list(a.enabled_tools),
                        "mcp_url_override": a.mcp_url_override,
                        "mcp_timeout_seconds": a.mcp_timeout_seconds,
                        "subscribes": list(a.subscribes),
                        "publishes": list(a.publishes),
                        "require_approval": a.require_approval,
                        "allow_changes": a.allow_changes,
                        "llm_timeout_seconds": a.llm_timeout_seconds,
                        "max_run_minutes": a.max_run_minutes,
                    }
                    for a in agents
                ],
            },
        )
        session.add(run)
        await session.commit()
        return run.id


async def running_run_id(databases: Databases) -> int | None:
    async with databases.app_session_factory() as session:
        result = await session.execute(select(AiRun.id).where(AiRun.status == "running").limit(1))
        return result.scalar_one_or_none()


_active: set[int] = set()
ORPHAN_GRACE_SECONDS = 60


async def reap_orphaned_runs(databases: Databases) -> None:
    """A run's task dies with its process, which would leave the row 'running'
    forever. Rather than blanket-marking every running row at startup (which
    would also kill a run owned by another live process sharing the database,
    e.g. a second instance that fails to bind the port), only reap rows this
    process is not running itself and that are past a short grace period."""
    cutoff = utcnow() - datetime.timedelta(seconds=ORPHAN_GRACE_SECONDS)
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiRun)
            .where(AiRun.status == "running", AiRun.started_at < cutoff, AiRun.id.not_in(_active))
            .values(status="error", error="Interrupted (the process running it exited)", finished_at=utcnow())
        )
        await session.commit()


class Recorder:
    """Shared by every agent in a run; the lock keeps step indexes unique."""

    def __init__(self, databases: Databases, run_id: int) -> None:
        self._databases = databases
        self._run_id = run_id
        self._idx = 0
        self._lock = asyncio.Lock()

    async def step(self, **fields: Any) -> None:
        async with self._lock, self._databases.app_session_factory() as session:
            session.add(AiRunStep(run_id=self._run_id, idx=self._idx, **fields))
            await session.commit()
            self._idx += 1

    async def add_tokens(self, prompt: int, completion: int) -> None:
        async with self._lock, self._databases.app_session_factory() as session:
            run = await session.get(AiRun, self._run_id)
            if run is not None:
                run.prompt_tokens += prompt
                run.completion_tokens += completion
                await session.commit()
