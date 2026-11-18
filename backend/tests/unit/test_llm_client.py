import httpx
import pytest

from app.llm import client
from app.llm.client import LLMRequestError, call_chat_completions, stream_chat_completions

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


def _patch_stream(monkeypatch: pytest.MonkeyPatch, status: int, body: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(
        client.httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)
    )


@pytest.mark.asyncio
async def test_stream_chat_completions_yields_each_sse_chunk_and_stops_at_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
        b"data: [DONE]\n\n"
    )
    _patch_stream(monkeypatch, 200, body)

    chunks = [
        c
        async for c in stream_chat_completions(
            base_url="http://llm.test/v1", api_key=None, model="m", messages=[]
        )
    ]

    assert [c["choices"][0]["delta"].get("content") for c in chunks[:2]] == ["Hel", "lo"]
    assert chunks[-1]["usage"] == {"prompt_tokens": 5, "completion_tokens": 2}


@pytest.mark.asyncio
async def test_stream_chat_completions_raises_on_an_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stream(monkeypatch, 500, b"")

    with pytest.raises(LLMRequestError):
        async for _ in stream_chat_completions(
            base_url="http://llm.test/v1", api_key=None, model="m", messages=[]
        ):
            pass
