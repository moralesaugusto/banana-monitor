"""Token accounting for every model call (agents and the chat assistant), kept per day, source, agent,
provider and model so it can be summed, broken down, priced and reset. Only counts are stored."""

import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.background import named_lock
from app.db.session import Databases
from app.domain.models import LlmUsage, utcnow
from app.llm.provider import OPENROUTER_BASE_URL
from app.logging_setup import get_logger

logger = get_logger(__name__)

CATALOG_TTL_SECONDS = 3600.0
_catalog: tuple[float, list[dict[str, Any]]] | None = None


async def record_usage(
    databases: Databases,
    *,
    source: str,
    agent: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Adds one model call. A failure here is logged and swallowed: losing a count must never fail the
    call that was just made. A reply with no usage block counts as a call without usage."""
    day = utcnow().date().isoformat()
    context = prompt_tokens + completion_tokens
    try:
        async with named_lock("llm-usage"), databases.app_session_factory() as session:
            row = await session.scalar(
                select(LlmUsage).where(
                    LlmUsage.day == day,
                    LlmUsage.source == source,
                    LlmUsage.agent == agent,
                    LlmUsage.provider == provider,
                    LlmUsage.model == model,
                )
            )
            if row is None:
                row = LlmUsage(
                    day=day,
                    source=source,
                    agent=agent,
                    provider=provider,
                    model=model,
                    calls=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    max_context_tokens=0,
                    calls_without_usage=0,
                )
                session.add(row)
            row.calls += 1
            row.prompt_tokens += prompt_tokens
            row.completion_tokens += completion_tokens
            row.max_context_tokens = max(row.max_context_tokens, context)
            if context == 0:
                row.calls_without_usage += 1
            await session.commit()
    except Exception:  # noqa: BLE001 - see docstring
        logger.warning("llm_usage_not_recorded", agent=agent, exc_info=True)


@dataclass
class Totals:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    max_context_tokens: int = 0
    calls_without_usage: int = 0

    def add(self, row: LlmUsage) -> None:
        self.calls += row.calls
        self.prompt_tokens += row.prompt_tokens
        self.completion_tokens += row.completion_tokens
        self.max_context_tokens = max(self.max_context_tokens, row.max_context_tokens)
        self.calls_without_usage += row.calls_without_usage


async def usage_rows(session: AsyncSession) -> list[LlmUsage]:
    return list((await session.scalars(select(LlmUsage).order_by(LlmUsage.day))).all())


async def reset_usage(session: AsyncSession) -> None:
    await session.execute(delete(LlmUsage))
    await session.commit()


async def first_day(session: AsyncSession) -> str | None:
    return await session.scalar(select(func.min(LlmUsage.day)))


async def openrouter_catalog() -> list[dict[str, Any]]:
    """OpenRouter's public model list (context length and price per token), cached for an hour."""
    global _catalog
    if _catalog is not None and time.monotonic() - _catalog[0] < CATALOG_TTL_SECONDS:
        return _catalog[1]
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(OPENROUTER_BASE_URL + "/models")
        response.raise_for_status()
        data = response.json().get("data", [])
    models = []
    for m in data:
        pricing = m.get("pricing") or {}
        try:
            price_in = float(pricing.get("prompt") or 0)
            price_out = float(pricing.get("completion") or 0)
        except ValueError:
            continue
        models.append(
            {
                "id": str(m["id"]),
                "name": str(m.get("name") or m["id"]),
                "context_length": int(m.get("context_length") or 0),
                "usd_per_million_in": price_in * 1_000_000,
                "usd_per_million_out": price_out * 1_000_000,
                "tools": "tools" in (m.get("supported_parameters") or []),
            }
        )
    _catalog = (time.monotonic(), models)
    return models
