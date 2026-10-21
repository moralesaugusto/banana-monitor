from typing import Any

import httpx


class HomebridgeAuthError(Exception):
    """Raised when the Homebridge UI login exchange fails or is malformed."""


class HomebridgeClient:
    """Thin async httpx wrapper over the Homebridge UI's HTTP API.

    Homebridge UI requires a login exchange (POST /api/auth/login ->
    access_token) rather than static Basic Auth; the plugin has no persisted
    state between polls (consistent with plugins being pure functions), so
    every poll logs in fresh and discards the token afterwards.
    """

    def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
        self._base_url = f"http://{host}:{port}"
        self._timeout = timeout

    async def login(self, client: httpx.AsyncClient, username: str, password: str) -> str:
        response = await client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        if response.status_code != 200:
            raise HomebridgeAuthError(f"Login failed with status {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise HomebridgeAuthError("Login response was not valid JSON") from exc
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise HomebridgeAuthError("Login response did not include an access_token")
        return str(token)

    async def get_optional(
        self, client: httpx.AsyncClient, path: str, token: str
    ) -> dict[str, Any] | list[Any] | None:
        """GETs an endpoint whose exact availability varies across Homebridge UI
        versions - a 404 is treated as "not present", not a failure."""
        response = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        result: dict[str, Any] | list[Any] = response.json()
        return result

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
