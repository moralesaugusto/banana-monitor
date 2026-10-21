from typing import Any

import httpx

from app.integrations.tls import httpx_verify


class OmadaApiError(Exception):
    """Raised for a non-2xx response, an errorCode!=0 payload, or a response
    whose JSON shape doesn't match what this client expects. Omada's exact
    Local/Standard Controller API v2 shape varies by controller version and is
    not independently verified against live infrastructure here - see the
    "known limitation" note in docs/integrations.md. The plugin treats any of
    these as a clean poll failure rather than letting an exception escape."""


class OmadaClient:
    """Thin async httpx wrapper over Omada's local controller API v2
    (login + token-based session), following the same "small async client
    module" pattern as proxmox/client.py rather than a sync SDK.

    Best-effort/defensive by design: every response is checked for a 2xx
    status and an errorCode of 0 before any field is read, and unexpected
    shapes raise OmadaApiError with a message that never includes response
    bodies (which could echo back the token) - only a short description.
    """

    def __init__(
        self, host: str, port: int, verify_tls: bool = True, timeout: float = 10.0, ca_pem: str = ""
    ) -> None:
        self._base_url = f"https://{host}:{port}"
        self._verify = httpx_verify(verify_tls, ca_pem)
        self._timeout = timeout

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, verify=self._verify, timeout=self._timeout)

    async def login(self, client: httpx.AsyncClient, username: str, password: str) -> str:
        response = await client.post(
            "/api/v2/login", json={"username": username, "password": password}
        )
        payload = self._unwrap(response)
        result = payload.get("result")
        token = result.get("token") if isinstance(result, dict) else None
        if not token:
            raise OmadaApiError("Login response did not include a session token")
        return str(token)

    async def resolve_site_id(
        self, client: httpx.AsyncClient, token: str, site_name: str
    ) -> str:
        response = await client.get(
            "/api/v2/sites",
            params={"currentPage": 1, "currentPageSize": 1000, "token": token},
            headers={"Csrf-Token": token},
        )
        payload = self._unwrap(response)
        sites = self._extract_list(payload.get("result"))
        if sites is None:
            raise OmadaApiError("Site list response had an unexpected shape")
        if not sites:
            raise OmadaApiError("Controller reported no sites")

        for site in sites:
            if isinstance(site, dict) and site.get("name") == site_name:
                site_id = site.get("siteId")
                if isinstance(site_id, str):
                    return site_id

        # Best-effort fallback: a single-site home controller commonly just has
        # "Default" - if the configured name doesn't match, use the first site
        # rather than failing outright, since most homelabs have exactly one.
        first = sites[0]
        site_id = first.get("siteId") if isinstance(first, dict) else None
        if isinstance(site_id, str):
            return site_id
        raise OmadaApiError(f"Could not resolve a site id for site {site_name!r}")

    async def dashboard_overview(
        self, client: httpx.AsyncClient, token: str, site_id: str
    ) -> dict[str, Any]:
        response = await client.get(
            f"/api/v2/sites/{site_id}/dashboard/overviewDiagram",
            params={"token": token},
            headers={"Csrf-Token": token},
        )
        payload = self._unwrap(response)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise OmadaApiError("Dashboard overview response had an unexpected shape")
        return result

    async def list_devices(
        self, client: httpx.AsyncClient, token: str, site_id: str
    ) -> list[dict[str, Any]]:
        response = await client.get(
            f"/api/v2/sites/{site_id}/devices",
            params={"token": token},
            headers={"Csrf-Token": token},
        )
        payload = self._unwrap(response)
        devices = self._extract_list(payload.get("result"))
        if devices is None:
            raise OmadaApiError("Device list response had an unexpected shape")
        return [d for d in devices if isinstance(d, dict)]

    def _unwrap(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code < 200 or response.status_code >= 300:
            raise OmadaApiError(f"Omada API returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OmadaApiError("Omada API response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise OmadaApiError("Omada API response was not a JSON object")
        error_code = payload.get("errorCode")
        if error_code not in (0, None):
            message = payload.get("msg") or "unknown error"
            raise OmadaApiError(f"Omada API error {error_code}: {message}")
        return payload

    @staticmethod
    def _extract_list(result: Any) -> list[Any] | None:
        """Different controller versions return either a bare list or a
        {"data": [...], "totalRows": N} page envelope for the same endpoint -
        accept either rather than guessing which one is live."""
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and isinstance(result.get("data"), list):
            data: list[Any] = result["data"]
            return data
        return None
