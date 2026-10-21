from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import AppSession, CredentialServiceDep, CredentialsSession
from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_telegram_config
from app.domain.enums import CredentialType
from app.domain.models import TelegramConfig
from app.telegram import client
from app.telegram.connection import load_connection

router = APIRouter(prefix="/telegram", tags=["telegram"])


class TelegramConfigRead(BaseModel):
    enabled: bool
    token_set: bool
    chat_ids: list[int]
    notify_alerts: bool
    notify_ai_reports: bool


class TelegramConfigUpdate(BaseModel):
    enabled: bool | None = None
    bot_token: str | None = None
    """Write-only: stored encrypted, never returned."""
    chat_ids: list[int] | None = None
    notify_alerts: bool | None = None
    notify_ai_reports: bool | None = None


def _read(config: TelegramConfig) -> TelegramConfigRead:
    return TelegramConfigRead(
        enabled=config.enabled,
        token_set=config.credential_id is not None,
        chat_ids=list(config.chat_ids),
        notify_alerts=config.notify_alerts,
        notify_ai_reports=config.notify_ai_reports,
    )


@router.get("/config", response_model=TelegramConfigRead)
async def get_config(session: AppSession) -> TelegramConfigRead:
    return _read(await ensure_default_telegram_config(session))


@router.put("/config", response_model=TelegramConfigRead)
async def update_config(
    payload: TelegramConfigUpdate,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> TelegramConfigRead:
    config = await ensure_default_telegram_config(session)
    token = (payload.bot_token or "").strip()
    if token:
        try:
            await client.call(token, "getMe", timeout=10.0)
        except client.TelegramError as exc:
            raise HTTPException(status_code=400, detail=f"Telegram rejected the bot token: {exc}") from exc
        old_id = config.credential_id
        credential = await credential_service.create(
            credentials_session, "Telegram bot token", CredentialType.API_TOKEN, {"token": token}
        )
        config.credential_id = credential.id
        if old_id is not None:
            await credential_service.delete(credentials_session, old_id)
    if payload.chat_ids is not None:
        config.chat_ids = payload.chat_ids
    if payload.notify_alerts is not None:
        config.notify_alerts = payload.notify_alerts
    if payload.notify_ai_reports is not None:
        config.notify_ai_reports = payload.notify_ai_reports
    if payload.enabled is not None:
        if payload.enabled and config.credential_id is None:
            raise HTTPException(status_code=400, detail="Set a bot token before enabling Telegram")
        config.enabled = payload.enabled
    await session.commit()
    await session.refresh(config)
    return _read(config)


@router.post("/test")
async def send_test() -> dict[str, int]:
    connection = await load_connection(get_databases())
    if connection is None:
        raise HTTPException(status_code=409, detail="Telegram is not enabled")
    if not connection.chat_ids:
        raise HTTPException(
            status_code=409, detail="No chat ids yet: message the bot, then add the id it replies with"
        )
    try:
        for chat_id in connection.chat_ids:
            await client.send_message(connection.token, chat_id, "Banana is connected.")
    except client.TelegramError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"sent": len(connection.chat_ids)}
