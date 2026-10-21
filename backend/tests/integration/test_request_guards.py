import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_databases
from app.domain.models import LoginAttempt, utcnow


@pytest.mark.asyncio
async def test_cross_origin_state_changes_are_refused_even_with_a_valid_session(client: AsyncClient) -> None:
    body = {"display_name": "box", "device_type": "other"}
    evil = await client.post("/api/devices", json=body, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403 and evil.json()["detail"] == "cross_origin_blocked"
    site = await client.post("/api/devices", json=body, headers={"Sec-Fetch-Site": "cross-site"})
    assert site.status_code == 403
    # Another port on the same machine is another origin too.
    port = await client.post("/api/devices", json=body, headers={"Origin": "http://test:5173"})
    assert port.status_code == 403

    same = await client.post("/api/devices", json=body, headers={"Origin": "http://test", "Host": "test"})
    assert same.status_code == 201
    assert (await client.post("/api/devices", json=body)).status_code == 201  # no Origin: not a browser
    assert (await client.get("/api/devices", headers={"Origin": "https://evil.example"})).status_code == 200


@pytest.mark.asyncio
async def test_login_is_protected_from_cross_origin_posts_too(anon_client: AsyncClient) -> None:
    login = {"username": "admin", "password": "admin"}
    response = await anon_client.post(
        "/api/auth/login", json=login, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_only_allowed_hosts_are_answered_when_configured(
    anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await anon_client.get("/api/health")).status_code == 200
    monkeypatch.setenv("BANANA_ALLOWED_HOSTS", "banana.lan, 10.0.0.5")
    from app.config import get_settings

    get_settings.cache_clear()
    assert (await anon_client.get("/api/health", headers={"Host": "evil.example"})).status_code == 400
    assert (await anon_client.get("/api/health", headers={"Host": "banana.lan:8000"})).status_code == 200
    assert (await anon_client.get("/api/health", headers={"Host": "10.0.0.5"})).status_code == 200


@pytest.mark.asyncio
async def test_security_headers_are_on_every_response(anon_client: AsyncClient) -> None:
    for path in ("/api/health", "/api/devices"):
        headers = (await anon_client.get(path)).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert "default-src 'self'" in headers["content-security-policy"]


@pytest.mark.asyncio
async def test_api_docs_are_off_unless_enabled(client: AsyncClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        body = (await client.get(path)).text
        assert "swagger" not in body.lower() and '"openapi"' not in body and "redoc" not in body.lower()


def test_api_docs_can_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setenv("BANANA_ENABLE_API_DOCS", "true")
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    assert app.openapi_url == "/openapi.json"


@pytest.mark.asyncio
async def test_the_login_lockout_survives_in_the_database_and_expires(anon_client: AsyncClient) -> None:
    login = {"username": "admin", "password": "nope"}
    for _ in range(5):
        await anon_client.post("/api/auth/login", json=login)
    assert (await anon_client.post("/api/auth/login", json={**login, "password": "admin"})).status_code == 429

    async with get_databases().app_session_factory() as session:
        rows = (await session.execute(select(LoginAttempt))).scalars().all()
        assert len(rows) == 1 and rows[0].locked_until is not None
        rows[0].locked_until = utcnow() - datetime.timedelta(seconds=1)
        await session.commit()
    assert (await anon_client.post("/api/auth/login", json={**login, "password": "admin"})).status_code == 200
