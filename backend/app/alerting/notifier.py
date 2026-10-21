from typing import Protocol

from app.db.session import Databases
from app.domain.enums import AlertSeverity, AlertState, EntityType, EventSeverity
from app.domain.models import AlertRule, Event
from app.logging_setup import get_logger

logger = get_logger(__name__)

_EVENT_SEVERITY_BY_RULE_SEVERITY: dict[AlertSeverity, EventSeverity] = {
    AlertSeverity.CRITICAL: EventSeverity.ERROR,
    AlertSeverity.WARNING: EventSeverity.WARNING,
    AlertSeverity.INFO: EventSeverity.INFO,
}


class Notifier(Protocol):
    async def notify(
        self,
        rule: AlertRule,
        entity_type: EntityType,
        entity_id: int,
        new_state: AlertState,
        value: float | None,
        message: str | None,
    ) -> None: ...


class LogNotifier:
    """Iteration-1 notification channel: a structured log line plus an Event row.

    Real channels (email/webhook) plug into the same Notifier protocol later.
    """

    def __init__(self, databases: Databases) -> None:
        self._databases = databases

    async def notify(
        self,
        rule: AlertRule,
        entity_type: EntityType,
        entity_id: int,
        new_state: AlertState,
        value: float | None,
        message: str | None,
    ) -> None:
        logger.info(
            "alert_transition",
            rule=rule.name,
            entity_type=entity_type.value,
            entity_id=entity_id,
            state=new_state.value,
            value=value,
        )

        severity = (
            _EVENT_SEVERITY_BY_RULE_SEVERITY[rule.severity]
            if new_state in (AlertState.FIRING, AlertState.FLAPPING)
            else EventSeverity.INFO
        )
        text = f"{rule.name}: {entity_type.value} {entity_id} -> {new_state.value}"
        if message:
            text += f" ({message})"

        async with self._databases.app_session_factory() as session:
            session.add(
                Event(
                    source="alerting",
                    severity=severity,
                    category="alert",
                    message=text,
                    related_entity_type=entity_type,
                    related_entity_id=entity_id,
                )
            )
            await session.commit()
