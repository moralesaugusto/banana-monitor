"""Latency of every agent's model calls, aggregated from AiRunStep - a companion to llm/usage.py's
token/cost accounting, answering "is agent X (or model Y) slower than another" rather than "what does
it cost". Unlike LlmUsage (a persistent counter table), this reads AiRunStep directly: a child of
AiRun, so clearing run history (AI Mode reset, or deleting runs) clears this too. A separate cutoff
(AiModeSettings.performance_reset_at) lets the Performance tab's own "Reset" button start the counters
over without touching AiRunStep or Run History at all."""

import datetime
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.domain.models import AiRunStep


@dataclass
class AgentLatency:
    agent: str
    models: list[str]
    calls: int
    errors: int
    avg_duration_ms: float
    min_duration_ms: int
    max_duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    tokens_per_second: float
    """completion_tokens / total time spent generating, across every counted call; 0 with no duration."""


@dataclass
class AgentModelLatency:
    agent: str
    model: str
    calls: int
    avg_duration_ms: float
    min_duration_ms: int
    max_duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    tokens_per_second: float


@dataclass
class ModelLatency:
    model: str
    agents: list[str]
    """Which agents have called this model - context for comparing it against what an agent uses today."""
    calls: int
    avg_duration_ms: float
    min_duration_ms: int
    max_duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    tokens_per_second: float


def _cutoff(cutoff: datetime.datetime | None) -> list[ColumnElement[bool]]:
    return [AiRunStep.ts >= cutoff] if cutoff else []


async def _llm_stats(
    session: AsyncSession, group_col: InstrumentedAttribute[str | None], cutoff: datetime.datetime | None
) -> Any:
    """One row per distinct value of group_col, counting only kind='llm' steps at or after cutoff."""
    return (
        await session.execute(
            select(
                group_col,
                func.count().label("calls"),
                func.sum(AiRunStep.duration_ms).label("total_duration_ms"),
                func.min(AiRunStep.duration_ms).label("min_duration_ms"),
                func.max(AiRunStep.duration_ms).label("max_duration_ms"),
                func.sum(AiRunStep.prompt_tokens).label("prompt_tokens"),
                func.sum(AiRunStep.completion_tokens).label("completion_tokens"),
            )
            .where(AiRunStep.kind == "llm", group_col.is_not(None), *_cutoff(cutoff))
            .group_by(group_col)
        )
    ).all()


async def agent_latency_rows(
    session: AsyncSession, cutoff: datetime.datetime | None = None
) -> list[AgentLatency]:
    stats = await _llm_stats(session, AiRunStep.agent, cutoff)
    models: dict[str, set[str]] = {}
    for agent, model in await session.execute(
        select(AiRunStep.agent, AiRunStep.name)
        .where(
            AiRunStep.kind == "llm",
            AiRunStep.agent.is_not(None),
            AiRunStep.name.is_not(None),
            *_cutoff(cutoff),
        )
        .distinct()
    ):
        models.setdefault(agent, set()).add(model)
    errors: dict[str, int] = {
        agent: count
        for agent, count in await session.execute(
            select(AiRunStep.agent, func.count())
            .where(AiRunStep.kind == "error", AiRunStep.agent.is_not(None), *_cutoff(cutoff))
            .group_by(AiRunStep.agent)
        )
        if agent is not None
    }
    rows = []
    for agent, calls, total_ms, min_ms, max_ms, prompt_tokens, completion_tokens in stats:
        total_ms = total_ms or 0
        rows.append(
            AgentLatency(
                agent=agent,
                models=sorted(models.get(agent, set())),
                calls=calls,
                errors=errors.get(agent, 0),
                avg_duration_ms=total_ms / calls if calls else 0.0,
                min_duration_ms=min_ms or 0,
                max_duration_ms=max_ms or 0,
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                tokens_per_second=(completion_tokens or 0) / (total_ms / 1000) if total_ms else 0.0,
            )
        )
    return sorted(rows, key=lambda r: -r.calls)


async def agent_model_latency_rows(
    session: AsyncSession, cutoff: datetime.datetime | None = None
) -> list[AgentModelLatency]:
    """One row per (agent, model) pair actually used - the breakdown for someone comparing models
    within a single agent, rather than an agent's blended average across every model it has ever used,
    or a model's blended average across every agent that has used it."""
    rows = await session.execute(
        select(
            AiRunStep.agent,
            AiRunStep.name,
            func.count().label("calls"),
            func.sum(AiRunStep.duration_ms).label("total_duration_ms"),
            func.min(AiRunStep.duration_ms).label("min_duration_ms"),
            func.max(AiRunStep.duration_ms).label("max_duration_ms"),
            func.sum(AiRunStep.prompt_tokens).label("prompt_tokens"),
            func.sum(AiRunStep.completion_tokens).label("completion_tokens"),
        )
        .where(
            AiRunStep.kind == "llm",
            AiRunStep.agent.is_not(None),
            AiRunStep.name.is_not(None),
            *_cutoff(cutoff),
        )
        .group_by(AiRunStep.agent, AiRunStep.name)
    )
    results = []
    for agent, model, calls, total_ms, min_ms, max_ms, prompt_tokens, completion_tokens in rows:
        total_ms = total_ms or 0
        results.append(
            AgentModelLatency(
                agent=agent,
                model=model,
                calls=calls,
                avg_duration_ms=total_ms / calls if calls else 0.0,
                min_duration_ms=min_ms or 0,
                max_duration_ms=max_ms or 0,
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                tokens_per_second=(completion_tokens or 0) / (total_ms / 1000) if total_ms else 0.0,
            )
        )
    return sorted(results, key=lambda r: (r.agent, -r.calls))


async def model_latency_rows(
    session: AsyncSession, cutoff: datetime.datetime | None = None
) -> list[ModelLatency]:
    """Per model, across every agent that has called it - so a model can be compared head to head
    before switching an agent to it, not just judged by whichever agent happens to use it today."""
    stats = await _llm_stats(session, AiRunStep.name, cutoff)
    agents: dict[str, set[str]] = {}
    for model, agent in await session.execute(
        select(AiRunStep.name, AiRunStep.agent)
        .where(
            AiRunStep.kind == "llm",
            AiRunStep.name.is_not(None),
            AiRunStep.agent.is_not(None),
            *_cutoff(cutoff),
        )
        .distinct()
    ):
        agents.setdefault(model, set()).add(agent)
    rows = []
    for model, calls, total_ms, min_ms, max_ms, prompt_tokens, completion_tokens in stats:
        total_ms = total_ms or 0
        rows.append(
            ModelLatency(
                model=model,
                agents=sorted(agents.get(model, set())),
                calls=calls,
                avg_duration_ms=total_ms / calls if calls else 0.0,
                min_duration_ms=min_ms or 0,
                max_duration_ms=max_ms or 0,
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                tokens_per_second=(completion_tokens or 0) / (total_ms / 1000) if total_ms else 0.0,
            )
        )
    return sorted(rows, key=lambda r: -r.calls)
