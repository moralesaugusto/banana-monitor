"""Minimal Telegram Bot API client (long polling, so no inbound port or public URL is needed).

The bot token is part of every request URL, so httpx errors (which print the URL) are never
propagated: they are turned into a TelegramError carrying only the error class."""

from typing import Any

import httpx

API = "https://api.telegram.org"
MESSAGE_LIMIT = 4096


class TelegramError(RuntimeError):
    pass


async def call(
    token: str,
    method: str,
    *,
    data: dict[str, Any] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: float = 30.0,
) -> Any:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{API}/bot{token}/{method}", data=data, files=files)
    except httpx.HTTPError as exc:
        raise TelegramError(f"{method} failed: {type(exc).__name__}") from None
    try:
        body = response.json()
    except ValueError:
        raise TelegramError(f"{method} failed: HTTP {response.status_code}") from None
    if not body.get("ok"):
        raise TelegramError(f"{method} failed: {body.get('description', response.status_code)}")
    return body["result"]


async def send_message(token: str, chat_id: int, text: str) -> None:
    text = text or "(empty reply)"
    for start in range(0, len(text), MESSAGE_LIMIT):
        chunk = text[start : start + MESSAGE_LIMIT]
        await call(token, "sendMessage", data={"chat_id": chat_id, "text": chunk})


async def send_document(token: str, chat_id: int, filename: str, content: bytes, caption: str = "") -> None:
    await call(
        token,
        "sendDocument",
        data={"chat_id": chat_id, "caption": caption[:1000]},
        files={"document": (filename, content, "application/pdf")},
        timeout=60.0,
    )
