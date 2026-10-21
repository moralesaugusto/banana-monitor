"""Clean-up actions for data that piles up, and the audit log of changes made through the API."""

import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select

from app.api.deps import AppSession, MetricsSession
from app.db.session import get_databases
from app.domain.metrics_models import CheckResult, MetricRollup, MetricSample
from app.domain.models import (
    AiMessage,
    AiMessageDelivery,
    AiRun,
    AiRunStep,
    AlertEvent,
    AlertStateRow,
    AuditEntry,
    Event,
    Report,
)
from app.llm.agent import running_run_id

router = APIRouter(tags=["maintenance"])

Target = Literal["reports", "events", "alerts", "bus", "history", "ai-runs"]


class CleanCounts(BaseModel):
    reports: int
    events: int
    alerts: int
    bus: int
    history: int
    ai_runs: int
    audit: int


class Deleted(BaseModel):
    deleted: int


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime.datetime
    actor: str
    method: str
    path: str
    status: int


async def _count(session: AppSession | MetricsSession, *models: type) -> int:
    total = 0
    for model in models:
        total += await session.scalar(select(func.count()).select_from(model)) or 0
    return total


@router.get("/maintenance/counts", response_model=CleanCounts)
async def counts(session: AppSession, metrics: MetricsSession) -> CleanCounts:
    return CleanCounts(
        reports=await _count(session, Report),
        events=await _count(session, Event),
        alerts=await _count(session, AlertStateRow, AlertEvent),
        bus=await _count(session, AiMessage),
        history=await _count(metrics, CheckResult, MetricSample, MetricRollup),
        ai_runs=await _count(session, AiRun),
        audit=await _count(session, AuditEntry),
    )


async def _delete(session: AppSession | MetricsSession, *models: type) -> int:
    total = 0
    for model in models:
        result = await session.execute(delete(model))
        total += result.rowcount  # type: ignore[attr-defined]
    await session.commit()
    return total


@router.delete("/maintenance/{target}", response_model=Deleted)
async def clean(target: Target, session: AppSession, metrics: MetricsSession) -> Deleted:
    """Alert rules and alert state are kept apart: `alerts` removes states and their transitions (a
    breach still in progress raises a fresh alert at the next evaluation), never the rules."""
    if target == "history":
        return Deleted(deleted=await _delete(metrics, CheckResult, MetricSample, MetricRollup))
    if target in ("bus", "ai-runs") and await running_run_id(get_databases()) is not None:
        raise HTTPException(status_code=409, detail="A run is active. Stop it first.")
    if target == "reports":
        return Deleted(deleted=await _delete(session, Report))
    if target == "events":
        return Deleted(deleted=await _delete(session, Event))
    if target == "alerts":
        return Deleted(deleted=await _delete(session, AlertEvent, AlertStateRow))
    if target == "bus":
        await _delete(session, AiMessageDelivery)
        return Deleted(deleted=await _delete(session, AiMessage))
    for model in (AiMessageDelivery, AiMessage, AiRunStep):
        await _delete(session, model)
    return Deleted(deleted=await _delete(session, AiRun))


@router.get("/audit", response_model=list[AuditRead])
async def list_audit(session: AppSession, limit: int = 200, offset: int = 0) -> list[AuditEntry]:
    rows = await session.scalars(
        select(AuditEntry).order_by(AuditEntry.id.desc()).limit(min(limit, 1000)).offset(offset)
    )
    return list(rows)


@router.delete("/audit", response_model=Deleted)
async def clean_audit(session: AppSession) -> Deleted:
    return Deleted(deleted=await _delete(session, AuditEntry))
