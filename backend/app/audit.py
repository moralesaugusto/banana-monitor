"""Records who changed what: every successful POST/PUT/PATCH/DELETE under /api by a signed-in user.
Pure ASGI, like the auth middleware, so streaming responses are untouched. Sits inside the auth
middleware, which tells it the user."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.db.session import get_databases
from app.domain.models import AuditEntry

CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in CHANGING_METHODS:
            await self.app(scope, receive, send)
            return
        status = 0

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        await self.app(scope, receive, capture)
        actor = scope.get("auth_user")
        if actor and 200 <= status < 400:
            async with get_databases().app_session_factory() as session:
                entry = AuditEntry(actor=actor, method=scope["method"], path=scope["path"], status=status)
                session.add(entry)
                await session.commit()
