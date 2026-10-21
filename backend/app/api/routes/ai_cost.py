"""Token usage of every model call (agents and chat), for estimating what the system costs to run."""

import datetime
from collections import defaultdict
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import AppSession
from app.domain.bootstrap import ensure_default_ai_mode_settings
from app.domain.models import utcnow
from app.llm.usage import Totals, first_day, openrouter_catalog, reset_usage, usage_rows

router = APIRouter(prefix="/ai-mode/cost", tags=["ai-cost"])


class UsageTotals(BaseModel):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    max_context_tokens: int = 0
    """Largest single call: prompt plus completion tokens."""
    calls_without_usage: int = 0
    """Calls whose reply carried no token counts (not included in the token sums)."""


class AgentUsage(UsageTotals):
    source: str
    agent: str
    models: list[str]


class ModelUsage(UsageTotals):
    provider: str
    model: str


class DayUsage(BaseModel):
    day: str
    calls: int
    prompt_tokens: int
    completion_tokens: int


class CostRead(BaseModel):
    since: datetime.datetime | None
    """When the counters were last reset; None if never."""
    first_day: str | None
    totals: UsageTotals
    by_agent: list[AgentUsage]
    by_model: list[ModelUsage]
    by_day: list[DayUsage]


class CatalogModel(BaseModel):
    id: str
    name: str
    context_length: int
    usd_per_million_in: float
    usd_per_million_out: float
    tools: bool


def _totals(t: Totals) -> dict[str, int]:
    return {
        "calls": t.calls,
        "prompt_tokens": t.prompt_tokens,
        "completion_tokens": t.completion_tokens,
        "total_tokens": t.prompt_tokens + t.completion_tokens,
        "max_context_tokens": t.max_context_tokens,
        "calls_without_usage": t.calls_without_usage,
    }


@router.get("", response_model=CostRead)
async def get_cost(session: AppSession) -> CostRead:
    settings = await ensure_default_ai_mode_settings(session)
    rows = await usage_rows(session)
    overall = Totals()
    agents: dict[tuple[str, str], Totals] = defaultdict(Totals)
    agent_models: dict[tuple[str, str], set[str]] = defaultdict(set)
    models: dict[tuple[str, str], Totals] = defaultdict(Totals)
    days: dict[str, Totals] = defaultdict(Totals)
    for row in rows:
        overall.add(row)
        agents[(row.source, row.agent)].add(row)
        agent_models[(row.source, row.agent)].add(row.model)
        models[(row.provider, row.model)].add(row)
        days[row.day].add(row)
    return CostRead(
        since=settings.usage_reset_at,
        first_day=await first_day(session),
        totals=UsageTotals(**_totals(overall)),
        by_agent=sorted(
            (
                AgentUsage(source=s, agent=a, models=sorted(agent_models[(s, a)]), **_totals(t))
                for (s, a), t in agents.items()
            ),
            key=lambda x: -x.total_tokens,
        ),
        by_model=sorted(
            (ModelUsage(provider=p, model=m, **_totals(t)) for (p, m), t in models.items()),
            key=lambda x: -x.total_tokens,
        ),
        by_day=[
            DayUsage(
                day=d, calls=t.calls, prompt_tokens=t.prompt_tokens, completion_tokens=t.completion_tokens
            )
            for d, t in sorted(days.items())
        ],
    )


@router.post("/reset", status_code=204)
async def reset_cost(session: AppSession) -> None:
    """Zeroes every counter and records when. Run history and traces keep their own token counts."""
    settings = await ensure_default_ai_mode_settings(session)
    await reset_usage(session)
    settings.usage_reset_at = utcnow()
    await session.commit()


@router.get("/openrouter-models", response_model=list[CatalogModel])
async def get_openrouter_models() -> list[dict[str, Any]]:
    """OpenRouter's public catalog (context length, price per million tokens) for pricing the usage above."""
    try:
        return await openrouter_catalog()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Could not load the OpenRouter catalog: {exc}") from exc
