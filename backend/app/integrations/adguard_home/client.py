from typing import Any

import httpx

from app.integrations.tls import httpx_verify

_TLS_PORTS = {443, 8443}


class AdGuardHomeClient:
    """Thin async httpx wrapper over the AdGuard Home control API, using HTTP
    Basic Auth like the rest of the vendor plugins' small client modules
    (proxmox/client.py, homebridge/client.py, omada/client.py).

    Scheme is inferred the same way discovery's TLS-port heuristic works
    (network_scanner.py's _TLS_PORTS): a well-known HTTPS port, `use_https` or a pinned certificate selects
    https - AdGuard Home's default web UI/API port (3000) is plain HTTP unless the user has fronted it with
    TLS themselves. Whether https is verified is `verify_tls` (default on) or the pinned certificate.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_tls: bool = True,
        timeout: float = 10.0,
        use_https: bool = False,
        ca_pem: str = "",
    ) -> None:
        scheme = "https" if use_https or ca_pem or port in _TLS_PORTS else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        self._auth = (username, password)
        self._verify = httpx_verify(verify_tls, ca_pem)
        self._timeout = timeout

    async def _get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            auth=self._auth,
            verify=self._verify,
            timeout=self._timeout,
        ) as client:
            response = await client.get(path)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

    async def status(self) -> dict[str, Any]:
        return await self._get("/control/status")

    async def stats(self) -> dict[str, Any]:
        return await self._get("/control/stats")
