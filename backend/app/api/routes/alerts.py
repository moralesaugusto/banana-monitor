from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import AppSession
from app.api.schemas.alerts import (
    AlertEventRead,
    AlertRuleCreate,
    AlertRuleRead,
    AlertRuleUpdate,
    AlertStateRead,
)
from app.domain.enums import AlertState
from app.domain.models import AlertEvent, AlertRule, AlertStateRow

router = APIRouter(prefix="/alerts", tags=["alerts"])


async def _get_rule_or_404(session: AppSession, rule_id: int) -> AlertRule:
    rule = await session.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return rule


@router.get("/rules", response_model=list[AlertRuleRead])
async def list_rules(session: AppSession) -> list[AlertRule]:
    result = await session.execute(select(AlertRule).order_by(AlertRule.name))
    return list(result.scalars().all())


@router.post("/rules", response_model=AlertRuleRead, status_code=201)
async def create_rule(payload: AlertRuleCreate, session: AppSession) -> AlertRule:
    rule = AlertRule(**payload.model_dump())
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.patch("/rules/{rule_id}", response_model=AlertRuleRead)
async def update_rule(rule_id: int, payload: AlertRuleUpdate, session: AppSession) -> AlertRule:
    rule = await _get_rule_or_404(session, rule_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, session: AppSession) -> None:
    rule = await _get_rule_or_404(session, rule_id)
    await session.delete(rule)
    await session.commit()


@router.get("/states", response_model=list[AlertStateRead])
async def list_states(session: AppSession, active_only: bool = True) -> list[AlertStateRow]:
    query = select(AlertStateRow).order_by(AlertStateRow.state_changed_at.desc())
    if active_only:
        query = query.where(AlertStateRow.state != AlertState.OK)
    result = await session.execute(query)
    return list(result.scalars().all())


@router.get("/states/{state_id}/events", response_model=list[AlertEventRead])
async def list_state_events(state_id: int, session: AppSession) -> list[AlertEvent]:
    result = await session.execute(
        select(AlertEvent).where(AlertEvent.alert_state_id == state_id).order_by(AlertEvent.ts.desc())
    )
    return list(result.scalars().all())
