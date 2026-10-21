"""Browser-facing request protections that sit in front of the authentication middleware: response
security headers, and rejection of cross-origin state-changing requests and unexpected Host values."""

from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.middleware import reject
from app.config import get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        b"connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'",
    ),
]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name for name, _ in message["headers"]}
                message["headers"] = [*message["headers"], *(h for h in HEADERS if h[0] not in present)]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return str(value.decode("latin-1"))
    return None


class OriginGuardMiddleware:
    """A browser tags every cross-origin request with Origin (and Sec-Fetch-Site), so a state-changing
    request whose Origin is not the host it was sent to is refused, whatever cookies it carries. Clients
    that send no Origin (curl, scripts) are not browsers and are left to the login. With
    BANANA_ALLOWED_HOSTS set, any other Host header is refused too, which stops DNS rebinding."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        host = (_header(scope, b"host") or "").lower()
        allowed = get_settings().allowed_host_list
        if allowed and host.rsplit(":", 1)[0].strip("[]") not in allowed:
            await reject(send, 400, "host_not_allowed")
            return

        if scope["method"] not in SAFE_METHODS and scope["path"].startswith("/api/"):
            origin = _header(scope, b"origin")
            cross_site = _header(scope, b"sec-fetch-site") == "cross-site"
            if cross_site or (origin is not None and urlsplit(origin).netloc.lower() != host):
                await reject(send, 403, "cross_origin_blocked")
                return
        await self.app(scope, receive, send)
