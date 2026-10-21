import asyncio
import weakref
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select

from app.alerting.notifier import LogNotifier, Notifier
from app.alerting.state_machine import AlertStateSnapshot, evaluate_transition
from app.db.session import Databases, get_databases
from app.domain.enums import AlertConditionType, AlertState, EntityType, IntegrationStatus
from app.domain.metrics_models import CheckResult
from app.domain.models import AlertEvent, AlertRule, AlertStateRow, Device, Integration, Service, utcnow
from app.metrics.queries import get_latest_metric_values
from app.telegram.notifier import TelegramNotifier

ALERT_SWEEP_INTERVAL_SECONDS = 30.0

DEFAULT_STALENESS_SECONDS = 90.0
DEFAULT_THRESHOLD = 90.0

_METRIC_NAME_BY_CONDITION: dict[AlertConditionType, str] = {
    AlertConditionType.HIGH_CPU: "cpu_percent",
    AlertConditionType.HIGH_MEMORY: "mem_used_percent",
    AlertConditionType.DISK_USAGE_HIGH: "disk_used_percent",
}

_ENTITY_TYPE_BY_CONDITION: dict[AlertConditionType, EntityType] = {
    AlertConditionType.DEVICE_DOWN: EntityType.DEVICE,
    AlertConditionType.HIGH_CPU: EntityType.DEVICE,
    AlertConditionType.HIGH_MEMORY: EntityType.DEVICE,
    AlertConditionType.DISK_USAGE_HIGH: EntityType.DEVICE,
    AlertConditionType.SERVICE_DOWN: EntityType.SERVICE,
    AlertConditionType.INTEGRATION_FAILING: EntityType.INTEGRATION,
}


def _applicable_entity_type(rule: AlertRule) -> EntityType | None:
    if rule.condition_type == AlertConditionType.METRIC_THRESHOLD:
        value = rule.parameters.get("entity_type")
        return EntityType(value) if value else None
    return _ENTITY_TYPE_BY_CONDITION.get(rule.condition_type)


def _matches_selector(selector: dict[str, Any], entity_type: EntityType, entity_id: int) -> bool:
    if selector.get("scope", "all") == "all":
        return True
    return entity_id in selector.get(f"{entity_type.value}_ids", [])


def _compare(value: float, comparator: str, threshold: float) -> bool:
    return {
        ">": value > threshold,
        ">=": value >= threshold,
        "<": value < threshold,
        "<=": value <= threshold,
        "==": value == threshold,
    }.get(comparator, False)


class AlertEngine:
    def __init__(self, databases: Databases, notifier: Notifier) -> None:
        self._databases = databases
        self._notifier = notifier
        # Weak values: an entry disappears once no evaluation holds its lock.
        self._locks: weakref.WeakValueDictionary[tuple[int, EntityType, int], asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    async def evaluate_entity(self, entity_type: EntityType, entity_id: int) -> None:
        async with self._databases.app_session_factory() as session:
            result = await session.execute(select(AlertRule).where(AlertRule.enabled.is_(True)))
            rules = list(result.scalars().all())

        for rule in rules:
            if _applicable_entity_type(rule) != entity_type:
                continue
            if not _matches_selector(rule.entity_selector, entity_type, entity_id):
                continue
            await self._evaluate_rule_for_entity(rule, entity_type, entity_id)

    async def run_staleness_sweep(self) -> None:
        async with self._databases.app_session_factory() as session:
            device_ids = [row[0] for row in (await session.execute(select(Device.id))).all()]
            service_ids = [row[0] for row in (await session.execute(select(Service.id))).all()]
            integration_ids = [row[0] for row in (await session.execute(select(Integration.id))).all()]

        for device_id in device_ids:
            await self.evaluate_entity(EntityType.DEVICE, device_id)
        for service_id in service_ids:
            await self.evaluate_entity(EntityType.SERVICE, service_id)
        for integration_id in integration_ids:
            await self.evaluate_entity(EntityType.INTEGRATION, integration_id)

    async def _evaluate_rule_for_entity(
        self, rule: AlertRule, entity_type: EntityType, entity_id: int
    ) -> None:
        # The state row is read, changed and written back; two evaluations of the same (rule, entity) at once
        # (a poll finishing while the sweep runs, or several targets of one integration) would both create
        # the row, or both record the same transition. Serialize them.
        key = (rule.id, entity_type, entity_id)
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        async with lock:
            await self._evaluate_locked(rule, entity_type, entity_id)

    async def _evaluate_locked(self, rule: AlertRule, entity_type: EntityType, entity_id: int) -> None:
        breach, current_value = await self._check_breach(rule, entity_type, entity_id)
        now = utcnow()

        async with self._databases.app_session_factory() as session:
            result = await session.execute(
                select(AlertStateRow).where(
                    AlertStateRow.alert_rule_id == rule.id,
                    AlertStateRow.entity_type == entity_type,
                    AlertStateRow.entity_id == entity_id,
                )
            )
            state_row = result.scalar_one_or_none()
            if state_row is None:
                state_row = AlertStateRow(
                    alert_rule_id=rule.id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    state=AlertState.OK,
                    state_changed_at=now,
                )
                session.add(state_row)
                await session.flush()

            params = rule.parameters or {}
            transition = evaluate_transition(
                AlertStateSnapshot(state_row.state, state_row.state_changed_at),
                breach,
                now,
                for_duration=params.get("for_duration_seconds", 60.0),
                recovery_duration=params.get("recovery_duration_seconds", 30.0),
            )

            new_state = transition.new_state
            should_notify = transition.should_notify
            flap_dampening = rule.flap_dampening or {}
            flap_window = flap_dampening.get("window_seconds", 600.0)
            flap_threshold = flap_dampening.get("threshold", 3)

            new_flap_score = state_row.flap_score
            if state_row.state == AlertState.RESOLVED and new_state == AlertState.FIRING:
                elapsed_since_last_flap = (now - state_row.state_changed_at).total_seconds()
                new_flap_score = state_row.flap_score + 1 if elapsed_since_last_flap < flap_window else 1
                if new_flap_score >= flap_threshold:
                    new_state = AlertState.FLAPPING
                    should_notify = False
            elif new_state == AlertState.OK:
                new_flap_score = 0.0

            state_changed = new_state != state_row.state
            if state_changed:
                session.add(
                    AlertEvent(
                        alert_state_id=state_row.id,
                        from_state=state_row.state,
                        to_state=new_state,
                        ts=now,
                        value_at_transition=current_value,
                        message=transition.message,
                    )
                )
                state_row.state_changed_at = now

            state_row.state = new_state
            state_row.last_evaluated_at = now
            state_row.current_value = current_value
            state_row.consecutive_breach_count = (
                state_row.consecutive_breach_count + 1 if breach else 0
            )
            state_row.flap_score = new_flap_score
            await session.commit()

        if state_changed and should_notify:
            await self._notifier.notify(
                rule, entity_type, entity_id, new_state, current_value, transition.message
            )

    async def _check_breach(
        self, rule: AlertRule, entity_type: EntityType, entity_id: int
    ) -> tuple[bool, float | None]:
        condition = rule.condition_type
        params = rule.parameters or {}

        if condition in (AlertConditionType.DEVICE_DOWN, AlertConditionType.SERVICE_DOWN):
            staleness_seconds = params.get("staleness_seconds", DEFAULT_STALENESS_SECONDS)
            last_success = await self._last_success_ts(entity_type, entity_id)
            if last_success is None:
                return True, None
            age = (utcnow() - last_success).total_seconds()
            return age > staleness_seconds, age

        if condition in _METRIC_NAME_BY_CONDITION:
            metric_name = _METRIC_NAME_BY_CONDITION[condition]
            threshold = params.get("threshold", DEFAULT_THRESHOLD)
            value = await self._latest_metric(entity_type, entity_id, metric_name)
            if value is None:
                return False, None
            return value > threshold, value

        if condition == AlertConditionType.METRIC_THRESHOLD:
            custom_metric_name = params.get("metric_name")
            custom_threshold = params.get("threshold")
            if custom_metric_name is None or custom_threshold is None:
                return False, None
            comparator = params.get("comparator", ">")
            value = await self._latest_metric(entity_type, entity_id, custom_metric_name)
            if value is None:
                return False, None
            return _compare(value, comparator, custom_threshold), value

        if condition == AlertConditionType.INTEGRATION_FAILING:
            async with self._databases.app_session_factory() as session:
                integration = await session.get(Integration, entity_id)
            return (integration is not None and integration.status == IntegrationStatus.ERROR), None

        return False, None

    async def _last_success_ts(self, entity_type: EntityType, entity_id: int):  # type: ignore[no-untyped-def]
        async with self._databases.metrics_session_factory() as session:
            result = await session.execute(
                select(func.max(CheckResult.ts)).where(
                    CheckResult.entity_type == entity_type,
                    CheckResult.entity_id == entity_id,
                    CheckResult.success.is_(True),
                )
            )
            return result.scalar_one_or_none()

    async def _latest_metric(
        self, entity_type: EntityType, entity_id: int, metric_name: str
    ) -> float | None:
        async with self._databases.metrics_session_factory() as session:
            values = await get_latest_metric_values(session, entity_type, metric_name, [entity_id])
            return values.get(entity_id)


@lru_cache
def get_alert_engine() -> AlertEngine:
    databases = get_databases()
    return AlertEngine(databases, TelegramNotifier(databases, LogNotifier(databases)))
