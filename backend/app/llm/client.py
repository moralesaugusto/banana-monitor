"""One HTTP call, shared by both providers.

Ollama's OpenAI-compatibility surface (`http://<host>:11434/v1`) and
OpenRouter (`https://openrouter.ai/api/v1`) both implement the same
`/chat/completions` contract, including OpenAI-style `tools`/`tool_calls`
function calling, so a single parameterized function covers both - no
per-provider client classes.
"""

from typing import Any

import httpx

DEFAULT_TIMEOUT_SECONDS = 60.0


class LLMRequestError(RuntimeError):
    pass


async def call_chat_completions(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """POSTs one OpenAI-compatible chat-completions request. Module-level
    function (not buried in a class) so tests can monkeypatch it directly -
    see app.discovery.oui.download_oui_csv for the same pattern."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    body: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        body["tools"] = tools
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        # One retry, for a server-side 500/502/503 only: a local Ollama answering several agents at once
        # returns an occasional 500 that a second attempt clears, and failing the call fails the agent.
        for attempt in (1, 2):
            try:
                response = await client.post("/chat/completions", json=body, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if attempt == 1 and exc.response.status_code in (500, 502, 503):
                    continue
                raise LLMRequestError(str(exc)) from exc
            except httpx.HTTPError as exc:
                detail = str(exc) or f"{type(exc).__name__} (no response within {timeout:.0f}s)"
                raise LLMRequestError(detail) from exc
            break
        data: dict[str, Any] = response.json()
        return data


async def list_models(base_url: str, timeout: float = 5.0) -> list[str]:
    """Model ids served by an OpenAI-compatible host (Ollama's `/v1/models`). Raises LLMRequestError."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(base_url.rstrip("/") + "/models")
            response.raise_for_status()
            return sorted(str(m["id"]) for m in response.json().get("data", []))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise LLMRequestError(str(exc) or type(exc).__name__) from exc
