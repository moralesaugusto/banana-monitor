"""One HTTP call: an OpenAI-compatible /embeddings request. Ollama already serves this
alongside /chat/completions on the same host - see app.llm.client.call_chat_completions
for the sibling call this mirrors."""

from typing import Any

import httpx

from app.llm.tool_base import AgentToolError

DEFAULT_TIMEOUT_SECONDS = 30.0


async def embed(base_url: str, model: str, text: str, *, api_key: str | None = None) -> list[float]:
    body = {"model": model, "input": text}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{base_url}/embeddings", json=body, headers=headers)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return list(data["data"][0]["embedding"])
    except httpx.HTTPError as exc:
        detail = str(exc) or f"{type(exc).__name__} (no response within {DEFAULT_TIMEOUT_SECONDS:.0f}s)"
        raise AgentToolError(f"embedding request failed: {detail}") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise AgentToolError(f"embedding response was not in the expected shape: {exc}") from exc
