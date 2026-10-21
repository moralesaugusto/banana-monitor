import pytest

from app.credentials.crypto import get_secret_box
from app.credentials.models import CredentialsBase
from app.credentials.service import CredentialService
from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_assistant_config
from app.domain.metrics_models import MetricsBase
from app.domain.models import Base as AppBase
from app.llm.client import LLMRequestError
from app.llm.service import AssistantService


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with dbs.metrics_engine.begin() as conn:
        await conn.run_sync(MetricsBase.metadata.create_all)
    async with dbs.credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


def _plain_reply(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


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


@pytest.mark.asyncio
async def test_plain_reply_with_no_tool_calls(databases, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(**kwargs: object) -> dict:
        return _plain_reply("Everything looks fine.")

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)

    async with (
        databases.app_session_factory() as session,
        databases.credentials_session_factory() as cred_session,
    ):
        await ensure_default_assistant_config(session)
        service = AssistantService(databases)
        credential_service = CredentialService(get_secret_box())
        reply = await service.send_chat_message(session, cred_session, credential_service, "how's it going?")

    assert reply.content == "Everything looks fine."
    assert reply.tool_calls is None


@pytest.mark.asyncio
async def test_one_tool_call_then_final_reply(databases, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = [
        _tool_call_reply("call_1", "list_devices", "{}"),
        _plain_reply("You have no devices yet."),
    ]

    async def fake(**kwargs: object) -> dict:
        return calls.pop(0)

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)

    async with (
        databases.app_session_factory() as session,
        databases.credentials_session_factory() as cred_session,
    ):
        await ensure_default_assistant_config(session)
        service = AssistantService(databases)
        credential_service = CredentialService(get_secret_box())
        reply = await service.send_chat_message(session, cred_session, credential_service, "list my devices")

    assert reply.content == "You have no devices yet."
    assert reply.tool_calls is not None
    assert reply.tool_calls[0]["name"] == "list_devices"
    assert reply.tool_calls[0]["result"] == []


@pytest.mark.asyncio
async def test_tool_call_limit_does_not_loop_forever(databases, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(**kwargs: object) -> dict:
        return _tool_call_reply("call_x", "list_devices", "{}")

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)

    async with (
        databases.app_session_factory() as session,
        databases.credentials_session_factory() as cred_session,
    ):
        (await ensure_default_assistant_config(session)).max_tool_iterations = 3
        await session.commit()
        service = AssistantService(databases)
        credential_service = CredentialService(get_secret_box())
        reply = await service.send_chat_message(session, cred_session, credential_service, "keep listing")

    assert len(reply.tool_calls) == 3
    assert "limit of 3 model calls" in reply.content


@pytest.mark.asyncio
async def test_unknown_tool_call_becomes_error_result_not_a_crash(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = [
        _tool_call_reply("call_1", "delete_everything", "{}"),
        _plain_reply("I can't do that."),
    ]

    async def fake(**kwargs: object) -> dict:
        return calls.pop(0)

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)

    async with (
        databases.app_session_factory() as session,
        databases.credentials_session_factory() as cred_session,
    ):
        await ensure_default_assistant_config(session)
        service = AssistantService(databases)
        credential_service = CredentialService(get_secret_box())
        reply = await service.send_chat_message(session, cred_session, credential_service, "delete stuff")

    assert reply.tool_calls[0]["result"]["error"]
    assert reply.content == "I can't do that."


@pytest.mark.asyncio
async def test_llm_request_error_propagates(databases, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(**kwargs: object) -> dict:
        raise LLMRequestError("connection refused")

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)

    async with (
        databases.app_session_factory() as session,
        databases.credentials_session_factory() as cred_session,
    ):
        await ensure_default_assistant_config(session)
        service = AssistantService(databases)
        credential_service = CredentialService(get_secret_box())
        with pytest.raises(LLMRequestError):
            await service.send_chat_message(session, cred_session, credential_service, "hello")
