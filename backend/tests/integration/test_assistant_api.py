import pytest
from httpx import AsyncClient

from app.llm.client import LLMRequestError


def _tool_call_reply(call_id: str, name: str, arguments: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": call_id, "function": {"name": name, "arguments": arguments}}
                    ],
                }
            }
        ]
    }


def _plain_reply(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


@pytest.mark.asyncio
async def test_get_config_returns_seeded_defaults(client: AsyncClient) -> None:
    response = await client.get("/api/assistant/config")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "ollama"
    assert body["base_url"] == "http://localhost:11434/v1"
    assert body["model"] == "qwen3:8b"
    assert body["credential_id"] is None
    assert body["full_access"] is False  # read-only by default


@pytest.mark.asyncio
async def test_put_config_openrouter_without_credential_is_rejected(client: AsyncClient) -> None:
    response = await client.put("/api/assistant/config", json={"provider": "openrouter"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_put_config_openrouter_with_valid_credential(client: AsyncClient) -> None:
    credential = (
        await client.post(
            "/api/credentials",
            json={"label": "openrouter", "credential_type": "api_token", "secret": {"token": "sk-test"}},
        )
    ).json()

    response = await client.put(
        "/api/assistant/config",
        json={"provider": "openrouter", "credential_id": credential["id"], "model": "openai/gpt-4o-mini"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openrouter"
    assert body["credential_id"] == credential["id"]
    assert body["model"] == "openai/gpt-4o-mini"


@pytest.mark.asyncio
async def test_chat_with_a_mocked_tool_call_persists_history(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = [
        _tool_call_reply("call_1", "list_devices", "{}"),
        _plain_reply("You have no devices."),
    ]

    async def fake(**kwargs: object) -> dict:
        return calls.pop(0)

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)

    response = await client.post("/api/assistant/chat", json={"message": "list my devices"})
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert reply["role"] == "assistant"
    assert reply["content"] == "You have no devices."
    assert reply["tool_calls"][0]["name"] == "list_devices"

    messages = (await client.get("/api/assistant/messages")).json()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "list my devices"
    assert messages[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_a_write_tool_is_refused_in_read_only_mode_by_default(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_tool_names: list[str] = []

    async def fake(**kwargs: object) -> dict:
        tools = kwargs["tools"]
        seen_tool_names.extend(t["function"]["name"] for t in tools)  # type: ignore[union-attr]
        call = {"id": "1", "function": {"name": "update_device", "arguments": '{"device_id": 1}'}}
        return {"choices": [{"message": {"content": "", "tool_calls": [call]}}]}

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)
    reply = (await client.post("/api/assistant/chat", json={"message": "rename device 1"})).json()["reply"]

    assert "update_device" not in seen_tool_names  # never even offered to the model
    assert "read-only mode" in reply["tool_calls"][0]["result"]["error"]


@pytest.mark.asyncio
async def test_full_access_allows_a_write_tool(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await client.put("/api/assistant/config", json={"full_access": True})
    seen_tool_names: list[str] = []

    async def fake(**kwargs: object) -> dict:
        tools = kwargs["tools"]
        seen_tool_names.extend(t["function"]["name"] for t in tools)  # type: ignore[union-attr]
        return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)
    await client.post("/api/assistant/chat", json={"message": "hi"})

    assert "update_device" in seen_tool_names
    assert "set_alert_rule_enabled" in seen_tool_names


@pytest.mark.asyncio
async def test_chat_llm_failure_returns_502(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_call(**kwargs: object) -> dict:
        raise LLMRequestError("no route to host")

    monkeypatch.setattr("app.llm.service.call_chat_completions", failing_call)

    response = await client.post("/api/assistant/chat", json={"message": "hi"})
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_clear_messages(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(**kwargs: object) -> dict:
        return _plain_reply("hi there")

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)
    await client.post("/api/assistant/chat", json={"message": "hello"})
    assert len((await client.get("/api/assistant/messages")).json()) == 2

    response = await client.delete("/api/assistant/messages")
    assert response.status_code == 204
    assert (await client.get("/api/assistant/messages")).json() == []


@pytest.mark.asyncio
async def test_chat_limits_are_tunable_and_used(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    body = (await client.get("/api/assistant/config")).json()
    assert body["max_tool_iterations"] == 8 and body["llm_timeout_seconds"] == 120

    limits = {"max_tool_iterations": 2, "llm_timeout_seconds": 300}
    saved = await client.put("/api/assistant/config", json=limits)
    assert saved.json()["max_tool_iterations"] == 2
    assert (await client.put("/api/assistant/config", json={"max_tool_iterations": 0})).status_code == 422
    assert (await client.put("/api/assistant/config", json={"llm_timeout_seconds": 5})).status_code == 422

    seen: list[object] = []

    async def always_tool(**kwargs: object) -> dict[str, object]:
        seen.append(kwargs["timeout"])
        call = {"id": "1", "function": {"name": "no_such_tool", "arguments": "{}"}}
        return {"choices": [{"message": {"content": "", "tool_calls": [call]}}]}

    monkeypatch.setattr("app.llm.service.call_chat_completions", always_tool)
    reply = (await client.post("/api/assistant/chat", json={"message": "hi"})).json()["reply"]
    assert seen == [300, 300]
    assert "limit of 2 model calls" in reply["content"]
