"""Requires a valid login session for the API. Pure ASGI (not BaseHTTPMiddleware) so server-sent
events stream through untouched."""

import json
from http.cookies import SimpleCookie

from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.service import SESSION_COOKIE, user_for_token
from app.db.session import get_databases

PUBLIC_PATHS = {"/api/health", "/api/auth/login"}
PASSWORD_CHANGE_PATHS = {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}
PROTECTED_PREFIXES = ("/api/", "/docs", "/redoc", "/openapi.json")


def _token(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"cookie":
            cookie: SimpleCookie = SimpleCookie()
            cookie.load(value.decode("latin-1"))
            morsel = cookie.get(SESSION_COOKIE)
            return morsel.value if morsel else None
    return None


async def reject(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path in PUBLIC_PATHS or not path.startswith(PROTECTED_PREFIXES):
            await self.app(scope, receive, send)
            return

        token = _token(scope)
        user = None
        if token:
            async with get_databases().app_session_factory() as session:
                user = await user_for_token(session, token)
        if user is None:
            await reject(send, 401, "Not signed in")
            return
        if user.must_change_password and path not in PASSWORD_CHANGE_PATHS:
            await reject(send, 403, "password_change_required")
            return
        scope["auth_user"] = user.username
        await self.app(scope, receive, send)
