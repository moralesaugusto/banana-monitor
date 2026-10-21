"""A service behind a self-signed certificate is up, not down; and Rescan re-checks its status."""

import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import uvicorn
from httpx import AsyncClient

from app.db.session import get_databases
from app.domain.models import Service
from app.integrations.base import TargetDescriptor
from app.integrations.http_tcp.plugin import HttpTcpPlugin
from app.tls import ensure_self_signed_certificate, hardened_uvicorn_config


async def _app(scope, receive, send) -> None:  # noqa: ANN001
    if scope["type"] != "http":
        return
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"2")]})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest_asyncio.fixture
async def https_port(tmp_path: Path) -> AsyncIterator[int]:
    cert, key = ensure_self_signed_certificate(tmp_path / "certs")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(hardened_uvicorn_config(_app, "127.0.0.1", port, cert, key))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    yield port
    server.should_exit = True
    await task


TARGET = TargetDescriptor(external_ref="1", display_name="x")


@pytest.mark.asyncio
async def test_an_untrusted_certificate_is_a_note_not_an_outage(https_port: int) -> None:
    result = await HttpTcpPlugin().poll({"url": f"https://127.0.0.1:{https_port}"}, None, TARGET)
    assert result.success is True and result.latency_ms is not None
    assert "certificate is not trusted" in (result.error_message or "")
    assert "self-signed" in (result.error_message or "")


@pytest.mark.asyncio
async def test_turning_verification_off_gives_no_note(https_port: int) -> None:
    config = {"url": f"https://127.0.0.1:{https_port}", "verify_tls": False}
    result = await HttpTcpPlugin().poll(config, None, TARGET)
    assert result.success is True and result.error_message is None


@pytest.mark.asyncio
async def test_a_service_that_really_is_down_is_still_down() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    result = await HttpTcpPlugin().poll({"url": f"https://127.0.0.1:{closed}"}, None, TARGET)
    assert result.success is False


@pytest.mark.asyncio
async def test_rescan_rechecks_the_service_and_reports_its_new_status(
    client: AsyncClient, https_port: int
) -> None:
    body = {"display_name": "d", "device_type": "other", "primary_ip": "127.0.0.1"}
    device = (await client.post("/api/devices", json=body)).json()
    service = (
        await client.post(
            "/api/services",
            json={
                "name": "web",
                "service_type": "https",
                "device_id": device["id"],
                "config": {"url": f"https://127.0.0.1:{https_port}"},
            },
        )
    ).json()
    assert service["status"] == "unknown"
    async with get_databases().app_session_factory() as session:
        (await session.get(Service, service["id"])).port = https_port  # as a discovered service has
        await session.commit()

    with patch("app.api.routes.services.rescan_device", AsyncMock(return_value=1)):
        response = await client.post(f"/api/services/{service['id']}/rescan")
    assert response.json() == {"updated": 1, "status": "up"}
    assert (await client.get(f"/api/services/{service['id']}")).json()["status"] == "up"

    with patch("app.api.routes.devices.rescan_device", AsyncMock(return_value=0)):
        assert (await client.post(f"/api/devices/{device['id']}/rescan")).status_code == 200
