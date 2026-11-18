import httpx
import pytest
import respx

from app.knowledge.embeddings import embed
from app.llm.tool_base import AgentToolError

BASE_URL = "http://ollama.local:11434/v1"


@pytest.mark.asyncio
@respx.mock
async def test_embed_posts_openai_shaped_request_and_returns_the_vector() -> None:
    route = respx.post(f"{BASE_URL}/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})
    )

    vector = await embed(BASE_URL, "nomic-embed-text", "hello world")

    assert vector == [0.1, 0.2, 0.3]
    sent = route.calls.last.request
    assert sent.url == f"{BASE_URL}/embeddings"
    import json

    assert json.loads(sent.content) == {"model": "nomic-embed-text", "input": "hello world"}


@pytest.mark.asyncio
@respx.mock
async def test_embed_sends_a_bearer_token_when_an_api_key_is_given() -> None:
    route = respx.post(f"{BASE_URL}/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
    )

    await embed(BASE_URL, "nomic-embed-text", "hello", api_key="sk-secret")

    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-secret"


@pytest.mark.asyncio
@respx.mock
async def test_embed_sends_no_auth_header_when_no_api_key_is_given() -> None:
    route = respx.post(f"{BASE_URL}/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
    )

    await embed(BASE_URL, "nomic-embed-text", "hello")

    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.asyncio
@respx.mock
async def test_embed_raises_agent_tool_error_on_a_non_2xx_response() -> None:
    respx.post(f"{BASE_URL}/embeddings").mock(return_value=httpx.Response(500, json={"error": "boom"}))

    with pytest.raises(AgentToolError):
        await embed(BASE_URL, "nomic-embed-text", "hello world")
