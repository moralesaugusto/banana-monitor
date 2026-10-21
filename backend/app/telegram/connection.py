from dataclasses import dataclass

from app.credentials.crypto import get_secret_box
from app.credentials.service import CredentialNotFoundError, CredentialService
from app.db.session import Databases
from app.domain.bootstrap import ensure_default_telegram_config


@dataclass
class Connection:
    token: str
    chat_ids: list[int]
    notify_alerts: bool
    notify_ai_reports: bool
    last_update_id: int


async def load_connection(databases: Databases) -> Connection | None:
    """The bot token (decrypted, held only in this object) and settings, or None when Telegram is
    switched off or has no token."""
    async with databases.app_session_factory() as session:
        config = await ensure_default_telegram_config(session)
        if not config.enabled or config.credential_id is None:
            return None
        credential_id = config.credential_id
        chat_ids = list(config.chat_ids)
        notify_alerts, last_update_id = config.notify_alerts, config.last_update_id
        notify_ai_reports = config.notify_ai_reports
    async with databases.credentials_session_factory() as session:
        try:
            secret = await CredentialService(get_secret_box()).get_decrypted(session, credential_id)
        except CredentialNotFoundError:
            return None
    token = secret.get("token")
    return (
        Connection(str(token), chat_ids, notify_alerts, notify_ai_reports, last_update_id)
        if token
        else None
    )
