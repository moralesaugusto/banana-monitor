from typing import Any

import httpx

from app.integrations.tls import httpx_verify


class ProxmoxClient:
    """Thin async wrapper over the Proxmox VE REST API using token auth.

    Kept on the same httpx stack as http_tcp/discovery for uniform timeout/TLS
    handling, rather than the sync `proxmoxer` library.
    """

    def __init__(
        self,
        host: str,
        port: int,
        token_id: str,
        token_secret: str,
        verify_tls: bool = True,
        timeout: float = 10.0,
        ca_pem: str = "",
    ) -> None:
        self._base_url = f"https://{host}:{port}/api2/json"
        self._headers = {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}
        self._verify = httpx_verify(verify_tls, ca_pem)
        self._timeout = timeout

    async def _get(self, path: str) -> Any:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            verify=self._verify,
            timeout=self._timeout,
        ) as client:
            response = await client.get(path)
            response.raise_for_status()
            return response.json()["data"]

    async def get(self, path: str) -> Any:
        """A read-only GET of any API path; callers decide which paths are allowed."""
        return await self._get(path)

    async def list_nodes(self) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = await self._get("/nodes")
        return data

    async def node_status(self, node: str) -> dict[str, Any]:
        data: dict[str, Any] = await self._get(f"/nodes/{node}/status")
        return data

    async def list_qemu(self, node: str) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = await self._get(f"/nodes/{node}/qemu")
        return data

    async def list_lxc(self, node: str) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = await self._get(f"/nodes/{node}/lxc")
        return data
