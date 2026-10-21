import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.enums import AlertConditionType, AlertSeverity, AlertState, EntityType


class AlertRuleCreate(BaseModel):
    name: str
    condition_type: AlertConditionType
    entity_selector: dict[str, Any] = {"scope": "all"}
    parameters: dict[str, Any] = {}
    severity: AlertSeverity = AlertSeverity.WARNING
    enabled: bool = True
    flap_dampening: dict[str, Any] = {}


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    entity_selector: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    severity: AlertSeverity | None = None
    enabled: bool | None = None
    flap_dampening: dict[str, Any] | None = None


class AlertRuleRead(AlertRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class AlertStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_rule_id: int
    entity_type: EntityType
    entity_id: int
    state: AlertState
    state_changed_at: datetime.datetime
    last_evaluated_at: datetime.datetime | None
    current_value: float | None
    consecutive_breach_count: int
    flap_score: float


class AlertEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_state_id: int
    from_state: AlertState
    to_state: AlertState
    ts: datetime.datetime
    value_at_transition: float | None
    message: str | None
