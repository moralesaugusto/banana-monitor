from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from app.llm.client import LLMRequestError

MODEL = "qwen:9b"


def _patch(
    monkeypatch: pytest.MonkeyPatch, *, models: list[str], tool_call: bool, fail_reply: bool = False
) -> list[Any]:
    keys: list[Any] = []

    async def fake_models(base_url: str, timeout: float = 5.0) -> list[str]:
        return models

    async def fake_chat(**kwargs: Any) -> dict[str, Any]:
        keys.append(kwargs["api_key"])
        if fail_reply:
            raise LLMRequestError("500 Internal Server Error")
        message: dict[str, Any] = {"content": "ok"}
        if kwargs.get("tools") and tool_call:
            message = {"content": "", "tool_calls": [{"function": {"name": "ping", "arguments": "{}"}}]}
        return {"choices": [{"message": message}]}

    monkeypatch.setattr("app.llm.connection_check.list_models", fake_models)
    monkeypatch.setattr("app.llm.connection_check.call_chat_completions", fake_chat)
    return keys


def _statuses(body: dict[str, Any]) -> dict[str, str]:
    return {c["id"]: c["status"] for c in body["checks"]}


@pytest.mark.asyncio
async def test_ollama_connection_passes(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, models=[MODEL], tool_call=True)
    response = await client.post(
        "/api/assistant/test", json={"base_url": "http://h:11434/v1", "model": MODEL}
    )
    body = response.json()
    assert body["ok"] is True
    assert _statuses(body) == {"host": "ok", "model": "ok", "reply": "ok", "tools": "ok"}


@pytest.mark.asyncio
async def test_missing_model_stops_before_calling_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = _patch(monkeypatch, models=["other"], tool_call=True)
    body = (await client.post("/api/assistant/test", json={"model": MODEL})).json()
    assert body["ok"] is False
    assert _statuses(body)["model"] == "fail"
    assert keys == []


@pytest.mark.asyncio
async def test_model_without_tool_calling_fails(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, models=[MODEL], tool_call=False)
    body = (await client.post("/api/assistant/test", json={"model": MODEL})).json()
    assert body["ok"] is False
    assert _statuses(body)["tools"] == "fail"


@pytest.mark.asyncio
async def test_server_error_from_the_host_is_reported(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, models=[MODEL], tool_call=True, fail_reply=True)
    body = (await client.post("/api/assistant/test", json={"model": MODEL})).json()
    reply = next(c for c in body["checks"] if c["id"] == "reply")
    assert reply["status"] == "fail" and "500" in reply["detail"]


class _FakeKeyClient:
    status = 200

    def __init__(self, **_: Any) -> None: ...

    async def __aenter__(self) -> "_FakeKeyClient":
        return self

    async def __aexit__(self, *_: Any) -> None: ...

    async def get(self, url: str, headers: dict[str, str]) -> httpx.Response:
        assert headers["Authorization"] == "Bearer sk-or-typed"
        return httpx.Response(self.status)


@pytest.mark.asyncio
async def test_openrouter_uses_the_typed_key_and_notes_agents(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = _patch(monkeypatch, models=[MODEL], tool_call=True)
    monkeypatch.setattr("app.llm.connection_check.httpx.AsyncClient", _FakeKeyClient)
    payload = {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": MODEL,
        "api_key": "sk-or-typed",
    }
    body = (await client.post("/api/assistant/test", json=payload)).json()
    assert body["ok"] is True
    assert _statuses(body) == {
        "key": "ok",
        "host": "ok",
        "model": "ok",
        "reply": "ok",
        "tools": "ok",
        "agents": "info",
    }
    assert set(keys) == {"sk-or-typed"}

    _FakeKeyClient.status = 401
    try:
        rejected = (await client.post("/api/assistant/test", json=payload)).json()
    finally:
        _FakeKeyClient.status = 200
    assert rejected["ok"] is False and _statuses(rejected)["key"] == "fail"
    assert "sk-or-typed" not in str(rejected)


@pytest.mark.asyncio
async def test_agents_use_their_own_default_llm_not_the_chat_assistants(client: AsyncClient) -> None:
    from app.db.session import get_databases
    from app.domain.models import AiRun
    from app.llm.agent import create_run

    await client.put(
        "/api/assistant/config", json={"base_url": "http://chat:11434/v1", "model": "chat-model"}
    )
    saved = await client.put(
        "/api/ai-mode/settings", json={"llm_base_url": "http://agents:11434/v1", "llm_model": "agent-model"}
    )
    assert saved.json()["llm_model"] == "agent-model"

    run_id = await create_run(get_databases(), targets=[], dry_run=True)
    async with get_databases().app_session_factory() as session:
        run = await session.get(AiRun, run_id)
    assert run is not None
    assert (run.base_url, run.model) == ("http://agents:11434/v1", "agent-model")
    assert (await client.get("/api/assistant/config")).json()["model"] == "chat-model"


@pytest.mark.asyncio
async def test_agent_default_llm_is_validated(client: AsyncClient) -> None:
    assert (await client.put("/api/ai-mode/settings", json={"llm_base_url": "not a url"})).status_code == 422
    assert (await client.put("/api/ai-mode/settings", json={"llm_model": ""})).status_code == 422
