"""How each tool has actually been used, read back from recorded run steps."""

import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.ai_mode import ToolUsage
from app.domain.models import AiRunStep


async def tool_usage(session: AsyncSession) -> list[ToolUsage]:
    """One entry per tool that has ever been called: counts, plus the latest call that worked and the
    latest one that was refused or failed, so a learner can see both what a tool does and what stops it."""
    stopped = AiRunStep.response["error"].as_string().is_not(None)
    is_tool = AiRunStep.kind == "tool"
    stats = await session.execute(
        select(AiRunStep.name, func.count(), func.sum(case((stopped, 1), else_=0)))
        .where(is_tool, AiRunStep.name.is_not(None))
        .group_by(AiRunStep.name)
    )
    totals = {name: (calls, int(errors or 0)) for name, calls, errors in stats.all()}
    if not totals:
        return []

    async def latest(condition: Any) -> dict[str, AiRunStep]:
        ids = select(func.max(AiRunStep.id)).where(is_tool, condition).group_by(AiRunStep.name)
        rows = await session.scalars(select(AiRunStep).where(AiRunStep.id.in_(ids)))
        return {row.name: row for row in rows if row.name}

    worked, refused = await latest(~stopped), await latest(stopped)
    usage = []
    for name, (calls, errors) in sorted(totals.items()):
        ok, bad = worked.get(name), refused.get(name)
        newest = max((s for s in (ok, bad) if s), key=lambda s: s.id)
        usage.append(
            ToolUsage(
                name=name,
                calls=calls,
                errors=errors,
                last_used=_aware(newest.ts),
                last_run_id=newest.run_id,
                worked_request=ok.request if ok else None,
                worked_response=ok.response if ok else None,
                worked_run_id=ok.run_id if ok else None,
                stopped_request=bad.request if bad else None,
                stopped_reason=str(bad.response.get("error")) if bad else None,
                stopped_run_id=bad.run_id if bad else None,
            )
        )
    return usage


def _aware(value: datetime.datetime) -> datetime.datetime:
    return value if value.tzinfo else value.replace(tzinfo=datetime.UTC)
