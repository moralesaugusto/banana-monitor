from urllib.parse import parse_qs

import pytest
import respx
from httpx import AsyncClient, Response

from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_agents
from app.llm.agent_tools import dispatch
from app.telegram.bot import handle_message, poll_once
from app.telegram.connection import load_connection


def _form(call) -> dict[str, str]:  # noqa: ANN001
    return {k: v[0] for k, v in parse_qs(call.request.content.decode()).items()}


TOKEN = "123456:tElEgRaM-tOkEn-do-not-leak"
API = f"https://api.telegram.org/bot{TOKEN}"


async def _device_with_service(client: AsyncClient) -> None:
    device = (
        await client.post(
            "/api/devices", json={"display_name": "pve1", "device_type": "linux", "primary_ip": "10.0.0.5"}
        )
    ).json()
    await client.post(
        "/api/services",
        json={
            "name": "web",
            "service_type": "tcp",
            "device_id": device["id"],
            "config": {"host": "10.0.0.5", "port": 80},
        },
    )


@pytest.mark.asyncio
async def test_snapshot_report_lists_devices_and_services_and_renders_pdf(client: AsyncClient) -> None:
    await _device_with_service(client)

    created = await client.post("/api/reports/snapshot")
    assert created.status_code == 201
    report = created.json()
    assert "pve1" in report["content"]
    assert "web" in report["content"]

    assert [r["id"] for r in (await client.get("/api/reports")).json()] == [report["id"]]
    pdf = await client.get(f"/api/reports/{report['id']}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    assert (await client.delete(f"/api/reports/{report['id']}")).status_code == 204
    assert (await client.get(f"/api/reports/{report['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_all_reports_clears_the_list(client: AsyncClient) -> None:
    await _device_with_service(client)
    first = (await client.post("/api/reports/snapshot")).json()
    second = (await client.post("/api/reports/snapshot")).json()
    assert len((await client.get("/api/reports")).json()) == 2

    assert (await client.delete("/api/reports")).status_code == 204
    assert (await client.get("/api/reports")).json() == []
    assert (await client.get(f"/api/reports/{first['id']}")).status_code == 404
    assert (await client.get(f"/api/reports/{second['id']}")).status_code == 404

    assert (await client.delete("/api/reports")).status_code == 204


@pytest.mark.asyncio
async def test_reporter_agent_is_seeded_and_can_save_a_report(client: AsyncClient) -> None:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    names = [a["name"] for a in (await client.get("/api/ai-mode/agents")).json()]
    assert "reporter" in names

    snapshot = await dispatch(databases, "get_network_snapshot", {}, enabled=["get_network_snapshot"])
    assert "devices" in snapshot
    saved = await dispatch(
        databases, "save_report", {"title": "T", "content": "## Hi"}, enabled=["save_report"]
    )
    assert saved["saved"] is True
    assert (await client.get(f"/api/reports/{saved['report_id']}")).json()["title"] == "T"

    dry = await dispatch(
        databases, "save_report", {"title": "T", "content": "x"}, enabled=["save_report"], dry_run=True
    )
    assert dry["saved"] is False


@pytest.mark.asyncio
async def test_save_report_captures_the_current_snapshot(client: AsyncClient) -> None:
    """So a later get_status_delta call has something to diff against."""
    databases = get_databases()
    await client.post(
        "/api/devices", json={"display_name": "web1", "device_type": "linux", "primary_ip": "10.0.0.5"}
    )
    saved = await dispatch(
        databases, "save_report", {"title": "T1", "content": "## Hi"}, enabled=["save_report"]
    )
    async with databases.app_session_factory() as session:
        from app.domain.models import Report

        report = await session.get(Report, saved["report_id"])
        assert report is not None
        assert report.snapshot is not None
        assert report.snapshot["devices"][0]["name"] == "web1"


@pytest.mark.asyncio
async def test_get_status_delta_with_no_prior_report(client: AsyncClient) -> None:
    databases = get_databases()
    result = await dispatch(databases, "get_status_delta", {}, enabled=["get_status_delta"])
    assert result["previous"] is None and result["delta"] is None
    assert "devices" in result["current"]


@pytest.mark.asyncio
async def test_get_status_delta_shows_what_changed_since_the_last_saved_report(client: AsyncClient) -> None:
    databases = get_databases()
    device = (
        await client.post(
            "/api/devices", json={"display_name": "web1", "device_type": "linux", "primary_ip": "10.0.0.5"}
        )
    ).json()
    first = await dispatch(
        databases, "save_report", {"title": "T1", "content": "## Hi"}, enabled=["save_report"]
    )

    await client.post(
        "/api/devices", json={"display_name": "web2", "device_type": "linux", "primary_ip": "10.0.0.6"}
    )
    result = await dispatch(databases, "get_status_delta", {}, enabled=["get_status_delta"])
    assert result["previous"]["report_id"] == first["report_id"]
    assert result["delta"]["devices_added"] == ["web2"]

    scoped = await dispatch(
        databases, "get_status_delta", {"hosts": ["10.0.0.5"]}, enabled=["get_status_delta"]
    )
    assert scoped["delta"]["devices_added"] == []  # the new device is outside the host scope
    assert [d["name"] for d in scoped["current"]["devices"]] == ["web1"]
    assert device["display_name"] == "web1"  # sanity check on the fixture itself


@pytest.mark.asyncio
async def test_get_network_snapshot_scopes_to_given_hosts(client: AsyncClient) -> None:
    """A reporter summarizing one host's result must be able to scope the snapshot to just that host,
    instead of always pulling the whole inventory into its prompt."""
    await client.post(
        "/api/devices", json={"display_name": "a", "device_type": "linux", "primary_ip": "10.0.0.5"}
    )
    await client.post(
        "/api/devices", json={"display_name": "b", "device_type": "linux", "primary_ip": "10.0.0.6"}
    )

    databases = get_databases()
    scoped = await dispatch(
        databases, "get_network_snapshot", {"hosts": ["10.0.0.5"]}, enabled=["get_network_snapshot"]
    )
    assert [d["ip"] for d in scoped["devices"]] == ["10.0.0.5"]
    assert scoped["unassigned_services"] == []

    full = await dispatch(databases, "get_network_snapshot", {}, enabled=["get_network_snapshot"])
    assert {d["ip"] for d in full["devices"]} == {"10.0.0.5", "10.0.0.6"}


@pytest.mark.asyncio
async def test_get_network_snapshot_truncates_a_large_unscoped_inventory(client: AsyncClient) -> None:
    """An unscoped call on an install with a large inventory must stay bounded and fast rather than
    risking the LLM call timeout - the single biggest known contributor to it."""
    from app.llm.agent_tools import MAX_SNAPSHOT_DEVICES

    for i in range(MAX_SNAPSHOT_DEVICES + 5):
        await client.post(
            "/api/devices",
            json={"display_name": f"d{i}", "device_type": "other", "primary_ip": f"10.1.0.{i}"},
        )

    snapshot = await dispatch(
        get_databases(), "get_network_snapshot", {}, enabled=["get_network_snapshot"]
    )
    assert len(snapshot["devices"]) == MAX_SNAPSHOT_DEVICES
    assert snapshot["devices_truncated"] is True
    assert snapshot["device_count_total"] == MAX_SNAPSHOT_DEVICES + 5


@pytest.mark.asyncio
@respx.mock
async def test_telegram_config_never_returns_the_token(client: AsyncClient) -> None:
    respx.post(f"{API}/getMe").mock(return_value=Response(200, json={"ok": True, "result": {}}))
    response = await client.put(
        "/api/telegram/config", json={"bot_token": TOKEN, "chat_ids": [42], "enabled": True}
    )
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True, "token_set": True, "chat_ids": [42],
        "notify_alerts": True, "notify_ai_reports": True,
    }
    for path in ("/api/telegram/config", "/api/credentials"):
        assert TOKEN not in (await client.get(path)).text


@pytest.mark.asyncio
@respx.mock
async def test_telegram_rejects_a_bad_token_and_enabling_without_one(client: AsyncClient) -> None:
    respx.post(f"{API}/getMe").mock(
        return_value=Response(401, json={"ok": False, "description": "Unauthorized"})
    )
    bad = await client.put("/api/telegram/config", json={"bot_token": TOKEN})
    assert bad.status_code == 400
    assert TOKEN not in bad.text
    assert (await client.put("/api/telegram/config", json={"enabled": True})).status_code == 400


@pytest.mark.asyncio
@respx.mock
async def test_telegram_bot_answers_only_allowed_chats(client: AsyncClient) -> None:
    respx.post(f"{API}/getMe").mock(return_value=Response(200, json={"ok": True, "result": {}}))
    await client.put("/api/telegram/config", json={"bot_token": TOKEN, "chat_ids": [42], "enabled": True})
    await _device_with_service(client)
    databases = get_databases()
    connection = await load_connection(databases)
    assert connection is not None

    send = respx.post(f"{API}/sendMessage").mock(return_value=Response(200, json={"ok": True, "result": {}}))
    document = respx.post(f"{API}/sendDocument").mock(
        return_value=Response(200, json={"ok": True, "result": {}})
    )

    await handle_message(databases, connection, 99, "/status")
    assert "Chat id: 99" in _form(send.calls.last)["text"]
    assert "Devices" not in _form(send.calls.last)["text"]

    await handle_message(databases, connection, 42, "/status")
    assert "Devices" in _form(send.calls.last)["text"]

    await handle_message(databases, connection, 42, "/report")
    assert document.called
    assert b"%PDF" in document.calls.last.request.content
    assert len((await client.get("/api/reports")).json()) == 1


@pytest.mark.asyncio
@respx.mock
async def test_automatic_report_push_is_gated_by_notify_ai_reports(client: AsyncClient) -> None:
    """send_report_to_chats is what notify_report_saved calls whenever any agent's save_report
    succeeds (an explicit /report ai, a scheduled run, or an automatic escalation chain) - turning
    notify_ai_reports off must stop that push without touching the saved report itself."""
    from app.telegram.bot import send_report_to_chats

    respx.post(f"{API}/getMe").mock(return_value=Response(200, json={"ok": True, "result": {}}))
    await client.put("/api/telegram/config", json={"bot_token": TOKEN, "chat_ids": [42], "enabled": True})
    report = (await client.post("/api/reports/snapshot")).json()
    document = respx.post(f"{API}/sendDocument").mock(
        return_value=Response(200, json={"ok": True, "result": {}})
    )

    await send_report_to_chats(get_databases(), report["id"])
    assert document.call_count == 1

    await client.put("/api/telegram/config", json={"notify_ai_reports": False})
    await send_report_to_chats(get_databases(), report["id"])
    assert document.call_count == 1  # unchanged: no push while off
    assert (await client.get(f"/api/reports/{report['id']}")).status_code == 200  # still saved


@pytest.mark.asyncio
@respx.mock
async def test_telegram_text_goes_to_the_assistant_and_polling_advances_the_offset(
    client: AsyncClient,
) -> None:
    respx.post(f"{API}/getMe").mock(return_value=Response(200, json={"ok": True, "result": {}}))
    await client.put("/api/telegram/config", json={"bot_token": TOKEN, "chat_ids": [42], "enabled": True})
    updates = respx.post(f"{API}/getUpdates").mock(
        return_value=Response(
            200,
            json={
                "ok": True,
                "result": [{"update_id": 7, "message": {"chat": {"id": 42}, "text": "how many devices?"}}],
            },
        )
    )
    respx.post(f"{API}/sendChatAction").mock(return_value=Response(200, json={"ok": True, "result": True}))
    send = respx.post(f"{API}/sendMessage").mock(return_value=Response(200, json={"ok": True, "result": {}}))
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "Two devices."}}]})
    )

    await poll_once(get_databases())
    assert _form(send.calls.last)["text"] == "Two devices."

    await poll_once(get_databases())
    assert _form(updates.calls.last)["offset"] == "8"
