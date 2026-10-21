import httpx
import pytest

from app.llm import client
from app.llm.client import LLMRequestError, call_chat_completions

_REAL_CLIENT = httpx.AsyncClient


def _patch(monkeypatch: pytest.MonkeyPatch, statuses: list[int]) -> list[int]:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses[len(seen)]
        seen.append(status)
        return httpx.Response(status, json={"choices": []})

    monkeypatch.setattr(
        client.httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)
    )
    return seen


async def _call() -> dict:
    return await call_chat_completions(base_url="http://llm.test/v1", api_key=None, model="m", messages=[])


@pytest.mark.asyncio
async def test_a_single_server_error_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch(monkeypatch, [500, 200])
    assert await _call() == {"choices": []}
    assert seen == [500, 200]


@pytest.mark.asyncio
async def test_a_repeated_server_error_fails_and_a_client_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch(monkeypatch, [500, 500])
    with pytest.raises(LLMRequestError):
        await _call()
    assert seen == [500, 500]

    seen = _patch(monkeypatch, [404])
    with pytest.raises(LLMRequestError):
        await _call()
    assert seen == [404]
