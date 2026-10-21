"""Checks that the configured Ollama or OpenRouter connection can run agents: the host answers, the key is
accepted, the model exists, it replies in reasonable time and it can call tools (agents depend on that)."""

import time
from typing import Any

import httpx

from app.api.schemas.ai_mode import VerifyCheck, VerifyResult
from app.domain.enums import AssistantProvider
from app.llm.client import LLMRequestError, call_chat_completions, list_models

REPLY_TIMEOUT_SECONDS = 60.0
SLOW_SECONDS = 20.0

PING_TOOL = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Replies pong. Call it when asked to ping.",
        "parameters": {"type": "object", "properties": {}},
    },
}


async def _check_key(base_url: str, api_key: str | None) -> VerifyCheck:
    if not api_key:
        return VerifyCheck(
            id="key", status="fail", title="No OpenRouter API key", detail="Enter or save a key."
        )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                base_url.rstrip("/") + "/auth/key", headers={"Authorization": f"Bearer {api_key}"}
            )
    except httpx.HTTPError as exc:
        return VerifyCheck(id="key", status="fail", title="OpenRouter is not reachable", detail=str(exc))
    if response.status_code in (401, 403):
        return VerifyCheck(id="key", status="fail", title="OpenRouter rejected the API key")
    if response.is_error:
        return VerifyCheck(
            id="key",
            status="fail",
            title="OpenRouter key check failed",
            detail=f"HTTP {response.status_code}",
        )
    return VerifyCheck(id="key", status="ok", title="OpenRouter accepted the API key")


async def _check_reply(base_url: str, api_key: str | None, model: str, timeout: float) -> VerifyCheck:
    started = time.monotonic()
    try:
        data = await call_chat_completions(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": "Reply with just: ok"}],
            timeout=timeout,
            max_tokens=16,
        )
    except LLMRequestError as exc:
        return VerifyCheck(id="reply", status="fail", title="Model did not respond", detail=str(exc))
    elapsed = time.monotonic() - started
    message: dict[str, Any] = (data.get("choices") or [{}])[0].get("message") or {}
    if not (message.get("content") or message.get("reasoning")):
        return VerifyCheck(id="reply", status="fail", title="Model returned an empty reply")
    if elapsed > SLOW_SECONDS:
        return VerifyCheck(
            id="reply",
            status="warn",
            title=f"Model is slow ({elapsed:.1f}s for a trivial reply)",
            detail="A real run sends much larger prompts and may exceed the model call timeout.",
        )
    return VerifyCheck(id="reply", status="ok", title=f"Model replied in {elapsed:.1f}s")


async def _check_tools(base_url: str, api_key: str | None, model: str, timeout: float) -> VerifyCheck:
    try:
        data = await call_chat_completions(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": "Call the ping tool."}],
            tools=[PING_TOOL],
            timeout=timeout,
            max_tokens=512,
        )
    except LLMRequestError as exc:
        return VerifyCheck(id="tools", status="fail", title="Tool calling request failed", detail=str(exc))
    message: dict[str, Any] = (data.get("choices") or [{}])[0].get("message") or {}
    calls = message.get("tool_calls") or []
    if any((call.get("function") or {}).get("name") == "ping" for call in calls):
        return VerifyCheck(id="tools", status="ok", title="Model can call tools")
    return VerifyCheck(
        id="tools",
        status="fail",
        title="Model did not call the test tool",
        detail="Agents work through tool calls; pick a model that supports tool calling.",
    )


async def check_connection(
    provider: AssistantProvider,
    base_url: str,
    model: str,
    api_key: str | None,
    timeout: float = REPLY_TIMEOUT_SECONDS,
) -> VerifyResult:
    checks: list[VerifyCheck] = []
    key = api_key if provider == AssistantProvider.OPENROUTER else None

    if provider == AssistantProvider.OPENROUTER:
        checks.append(await _check_key(base_url, key))
    try:
        models = await list_models(base_url, timeout=10)
    except LLMRequestError as exc:
        checks.append(
            VerifyCheck(id="host", status="fail", title="Host is not reachable", detail=f"{base_url}: {exc}")
        )
        return VerifyResult(ok=False, checks=checks)
    checks.append(
        VerifyCheck(
            id="host", status="ok", title="Host answers", detail=f"{base_url} lists {len(models)} model(s)."
        )
    )

    if model not in models:
        shown = ", ".join(models[:10]) + (" ..." if len(models) > 10 else "")
        checks.append(
            VerifyCheck(
                id="model",
                status="fail",
                title=f"Model {model} is not available",
                detail=f"Available: {shown or 'none'}.",
            )
        )
        return VerifyResult(ok=False, checks=checks)
    checks.append(VerifyCheck(id="model", status="ok", title=f"Model {model} is available"))

    if all(c.status != "fail" for c in checks):
        checks.append(await _check_reply(base_url, key, model, timeout))
        checks.append(await _check_tools(base_url, key, model, timeout))
    if provider == AssistantProvider.OPENROUTER:
        checks.append(
            VerifyCheck(
                id="agents",
                status="info",
                title="AI Mode agents run on Ollama",
                detail="This connection serves the chat assistant; agents use the Ollama provider.",
            )
        )
    return VerifyResult(ok=all(c.status != "fail" for c in checks), checks=checks)
