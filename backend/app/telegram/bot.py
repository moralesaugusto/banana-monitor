"""The Telegram bot: long-polls for messages from the allowed chats and answers them.

Plain text goes to the chat assistant (the same agent as the chat panel, with the same history).
Commands: /status, /report (PDF of the current state, built without a model), /report ai (starts the
reporter agent; its report is sent here when it is saved), /help. A chat that is not on the allowed
list is told its chat id and nothing else, so adding it in Settings is one copy and paste."""

import asyncio
from typing import Any

from fastapi import HTTPException

from app.api.schemas.ai_mode import AiRunStart
from app.background import spawn
from app.db.session import Databases
from app.domain.models import Report, TelegramConfig
from app.logging_setup import get_logger
from app.reports.builder import build_snapshot, default_title, snapshot_markdown
from app.reports.pdf import markdown_to_pdf
from app.telegram import client
from app.telegram.connection import Connection, load_connection

logger = get_logger(__name__)

POLL_TIMEOUT_SECONDS = 20
POLL_INTERVAL_SECONDS = 2.0

HELP = (
    "Banana\n"
    "Send any message to talk to the assistant.\n"
    "/status - devices, services and alerts right now\n"
    "/report - PDF report of the network and services\n"
    "/report ai - the reporter agent writes one (sent here when ready)\n"
    "/help - this text"
)


async def _save_snapshot_report(databases: Databases, source: str) -> Report:
    snapshot = await build_snapshot(databases)
    async with databases.app_session_factory() as session:
        report = Report(
            title=default_title(), source=source, content=snapshot_markdown(snapshot), snapshot=snapshot
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report


async def send_report(connection: Connection, chat_id: int, report: Report) -> None:
    await client.send_document(
        connection.token,
        chat_id,
        f"report-{report.id}.pdf",
        markdown_to_pdf(report.title, report.content),
        caption=report.title,
    )


async def send_report_to_chats(databases: Databases, report_id: int) -> None:
    """Pushes a saved report to every allowed chat - called whenever any AI Mode agent's save_report
    succeeds, whether from an explicit /report ai, a scheduled run, or an automatic escalation chain
    (e.g. reviewer -> bellaco/sinverguenza -> reporter). Gated by notify_ai_reports: off, the report is
    still saved and visible on the Reports page, just not pushed here."""
    connection = await load_connection(databases)
    if connection is None or not connection.notify_ai_reports:
        return
    async with databases.app_session_factory() as session:
        report = await session.get(Report, report_id)
    if report is None:
        return
    for chat_id in connection.chat_ids:
        try:
            await send_report(connection, chat_id, report)
        except client.TelegramError as exc:
            logger.warning("telegram_report_send_failed", chat_id=chat_id, error=str(exc))


async def _status_text(databases: Databases) -> str:
    snapshot = await build_snapshot(databases)
    dc, sc = snapshot["device_counts"], snapshot["service_counts"]
    down = [d["name"] for d in snapshot["devices"] if d["status"] == "down"]
    return (
        f"Devices: {dc['up']} up, {dc['degraded']} partial, {dc['down']} down, {dc['unknown']} unknown\n"
        f"Services: {sc['up']} up, {sc['degraded']} degraded, {sc['down']} down, {sc['unknown']} unknown\n"
        f"Active alerts: {len(snapshot['active_alerts'])}\n"
        f"Down: {', '.join(down) if down else 'nothing'}"
    )


async def _ask_assistant(databases: Databases, text: str) -> str:
    # Imported here: the assistant pulls in the scheduler and alerting, which import the notifier.
    from app.credentials.crypto import get_secret_box
    from app.credentials.service import CredentialService
    from app.llm.client import LLMRequestError
    from app.llm.service import AssistantService

    async with databases.app_session_factory() as session, databases.credentials_session_factory() as creds:
        try:
            reply = await AssistantService(databases).send_chat_message(
                session, creds, CredentialService(get_secret_box()), text
            )
        except LLMRequestError as exc:
            return f"The assistant is unavailable: {exc}"
    return reply.content


async def _start_ai_report(databases: Databases) -> str:
    from app.api.routes.ai_mode import start_run

    async with databases.app_session_factory() as session:
        try:
            run = await start_run(
                AiRunStart(entry_agent="reporter", message="Write the network and services report."), session
            )
        except HTTPException as exc:
            return f"Could not start the reporter: {exc.detail}"
    return (
        f"Reporter started (run {run.id}). The PDF is sent here when it is ready, unless automatic "
        "report delivery is off under Settings > Telegram - it is saved on the Reports page either way."
    )


async def handle_message(databases: Databases, connection: Connection, chat_id: int, text: str) -> None:
    if chat_id not in connection.chat_ids:
        await client.send_message(
            connection.token,
            chat_id,
            f"This chat is not authorized. Chat id: {chat_id}\nAdd it under Settings > Telegram in Banana.",
        )
        return
    command, _, argument = text.strip().partition(" ")
    command = command.split("@")[0].lower()
    if command in ("/start", "/help"):
        await client.send_message(connection.token, chat_id, HELP)
    elif command == "/status":
        await client.send_message(connection.token, chat_id, await _status_text(databases))
    elif command == "/report" and argument.strip().lower() == "ai":
        await client.send_message(connection.token, chat_id, await _start_ai_report(databases))
    elif command == "/report":
        await send_report(connection, chat_id, await _save_snapshot_report(databases, "telegram"))
    else:
        await client.call(connection.token, "sendChatAction", data={"chat_id": chat_id, "action": "typing"})
        await client.send_message(connection.token, chat_id, await _ask_assistant(databases, text))


async def _save_offset(databases: Databases, update_id: int) -> None:
    async with databases.app_session_factory() as session:
        config = await session.get(TelegramConfig, 1)
        if config is not None:
            config.last_update_id = update_id
            await session.commit()


async def poll_once(databases: Databases) -> None:
    connection = await load_connection(databases)
    if connection is None:
        return
    updates: list[dict[str, Any]] = await client.call(
        connection.token,
        "getUpdates",
        data={"offset": connection.last_update_id + 1, "timeout": POLL_TIMEOUT_SECONDS},
        timeout=POLL_TIMEOUT_SECONDS + 10,
    )
    for update in updates:
        # The offset is saved before the message is handled, so a message that makes the handler fail is
        # not retried forever.
        await _save_offset(databases, update["update_id"])
        message = update.get("message") or {}
        text = message.get("text")
        if not text:
            continue
        chat_id = message["chat"]["id"]
        try:
            await handle_message(databases, connection, chat_id, text)
        except client.TelegramError as exc:
            logger.warning("telegram_reply_failed", chat_id=chat_id, error=str(exc))
        except Exception:
            logger.exception("telegram_handler_failed", chat_id=chat_id)
            await asyncio.shield(
                client.send_message(connection.token, chat_id, "Something went wrong handling that message.")
            )


def notify_report_saved(databases: Databases, report_id: int) -> None:
    spawn(send_report_to_chats(databases, report_id), f"telegram-report-{report_id}")
