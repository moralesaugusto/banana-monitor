from app.alerting.notifier import Notifier
from app.db.session import Databases
from app.domain.enums import AlertState, EntityType
from app.domain.models import AlertRule
from app.logging_setup import get_logger
from app.telegram import client
from app.telegram.connection import load_connection

logger = get_logger(__name__)


class TelegramNotifier:
    """Runs the wrapped notifier, then sends the transition to the allowed Telegram chats. A failed
    send is logged and never affects alert evaluation."""

    def __init__(self, databases: Databases, inner: Notifier) -> None:
        self._databases = databases
        self._inner = inner

    async def notify(
        self,
        rule: AlertRule,
        entity_type: EntityType,
        entity_id: int,
        new_state: AlertState,
        value: float | None,
        message: str | None,
    ) -> None:
        await self._inner.notify(rule, entity_type, entity_id, new_state, value, message)
        connection = await load_connection(self._databases)
        if connection is None or not connection.notify_alerts:
            return
        text = f"[{new_state.value}] {rule.name}: {entity_type.value} {entity_id}"
        if message:
            text += f" ({message})"
        for chat_id in connection.chat_ids:
            try:
                await client.send_message(connection.token, chat_id, text)
            except client.TelegramError as exc:
                logger.warning("telegram_alert_send_failed", chat_id=chat_id, error=str(exc))
