import pytest
from httpx import AsyncClient

from app.auth.service import MAX_FAILURES


async def _login(client: AsyncClient, password: str = "admin") -> object:
    return await client.post("/api/auth/login", json={"username": "admin", "password": password})


@pytest.mark.asyncio
async def test_the_api_requires_a_login_but_health_does_not(anon_client: AsyncClient) -> None:
    assert (await anon_client.get("/api/health")).status_code == 200
    for path in ("/api/devices", "/api/credentials", "/api/auth/me", "/openapi.json"):
        assert (await anon_client.get(path)).status_code == 401, path


@pytest.mark.asyncio
async def test_default_admin_must_change_the_password_before_anything_else(anon_client: AsyncClient) -> None:
    login = await _login(anon_client)
    assert login.status_code == 200
    assert login.json() == {"username": "admin", "must_change_password": True}
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie

    assert (await anon_client.get("/api/auth/me")).status_code == 200
    blocked = await anon_client.get("/api/devices")
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"

    wrong = await anon_client.post(
        "/api/auth/password", json={"current_password": "nope", "new_password": "x"}
    )
    assert wrong.status_code == 400

    # No complexity rules: one character is fine.
    changed = await anon_client.post(
        "/api/auth/password", json={"current_password": "admin", "new_password": "x"}
    )
    assert changed.status_code == 200 and changed.json()["must_change_password"] is False
    assert (await anon_client.get("/api/devices")).status_code == 200

    anon_client.cookies.clear()
    assert (await _login(anon_client, "admin")).status_code == 401
    assert (await _login(anon_client, "x")).status_code == 200


@pytest.mark.asyncio
async def test_the_new_password_may_be_the_same_as_the_current_one(anon_client: AsyncClient) -> None:
    await _login(anon_client)
    same = await anon_client.post(
        "/api/auth/password", json={"current_password": "admin", "new_password": "admin"}
    )
    assert same.status_code == 200 and same.json()["must_change_password"] is False
    assert (await anon_client.get("/api/devices")).status_code == 200


@pytest.mark.asyncio
async def test_changing_the_password_ends_other_sessions(anon_client: AsyncClient) -> None:
    await _login(anon_client)
    old_cookie = anon_client.cookies.get("banana_session")
    await anon_client.post("/api/auth/password", json={"current_password": "admin", "new_password": "secret"})
    assert anon_client.cookies.get("banana_session") != old_cookie
    anon_client.cookies.set("banana_session", old_cookie or "")
    assert (await anon_client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_logout_ends_the_session(anon_client: AsyncClient) -> None:
    await _login(anon_client)
    token = anon_client.cookies.get("banana_session")
    assert (await anon_client.post("/api/auth/logout")).status_code == 204
    anon_client.cookies.set("banana_session", token or "")
    assert (await anon_client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_repeated_wrong_passwords_lock_the_login_for_a_while(anon_client: AsyncClient) -> None:
    for _ in range(MAX_FAILURES):
        assert (await _login(anon_client, "wrong")).status_code == 401
    assert (await _login(anon_client, "admin")).status_code == 429


@pytest.mark.asyncio
async def test_a_signed_in_client_can_use_the_api(client: AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).json() == {"username": "admin", "must_change_password": False}
    assert (await client.get("/api/devices")).status_code == 200


@pytest.mark.asyncio
async def test_no_response_ever_contains_a_password_hash(anon_client: AsyncClient) -> None:
    responses = [
        await _login(anon_client),
        await anon_client.get("/api/auth/me"),
        await anon_client.post("/api/auth/password", json={"current_password": "admin", "new_password": "z"}),
    ]
    for response in responses:
        assert "scrypt" not in response.text and "password_hash" not in response.text
