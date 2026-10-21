"""Per-agent and per-model latency, so a slower agent/model/host combination is visible rather than
just assumed - the performance companion to ai_cost.py's token/cost accounting."""

import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import AppSession
from app.domain.bootstrap import ensure_default_ai_mode_settings
from app.domain.models import utcnow
from app.llm.performance import agent_latency_rows, agent_model_latency_rows, model_latency_rows

router = APIRouter(prefix="/ai-mode/performance", tags=["ai-performance"])


class AgentPerformance(BaseModel):
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


class AgentModelPerformance(BaseModel):
    agent: str
    model: str
    calls: int
    avg_duration_ms: float
    min_duration_ms: int
    max_duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    tokens_per_second: float


class ModelPerformance(BaseModel):
    model: str
    agents: list[str]
    calls: int
    avg_duration_ms: float
    min_duration_ms: int
    max_duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    tokens_per_second: float


class PerformanceRead(BaseModel):
    since: datetime.datetime | None
    """When the Performance tab's own "Reset" was last pressed; None if never. Unrelated to Cost's
    `since` - resetting one does not reset the other."""
    by_agent: list[AgentPerformance]
    by_agent_model: list[AgentModelPerformance]
    """One row per (agent, model) pair actually used - the breakdown within a single agent across
    whichever models it has been run with, as opposed to by_agent's blended average."""
    by_model: list[ModelPerformance]


@router.get("", response_model=PerformanceRead)
async def get_performance(session: AppSession) -> PerformanceRead:
    settings = await ensure_default_ai_mode_settings(session)
    cutoff = settings.performance_reset_at
    agents = await agent_latency_rows(session, cutoff)
    agent_models = await agent_model_latency_rows(session, cutoff)
    models = await model_latency_rows(session, cutoff)
    return PerformanceRead(
        since=cutoff,
        by_agent=[AgentPerformance(**vars(r)) for r in agents],
        by_agent_model=[AgentModelPerformance(**vars(r)) for r in agent_models],
        by_model=[ModelPerformance(**vars(r)) for r in models],
    )


@router.post("/reset", status_code=204)
async def reset_performance(session: AppSession) -> None:
    """Starts the latency counters over without touching AiRunStep or Run History at all - it only
    moves the cutoff every query filters on."""
    settings = await ensure_default_ai_mode_settings(session)
    settings.performance_reset_at = utcnow()
    await session.commit()
