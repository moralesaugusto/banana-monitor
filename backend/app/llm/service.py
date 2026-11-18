"""Chat-turn orchestration: one user message -> a bounded tool-calling loop
against the configured LLM -> one persisted assistant reply.

`send_chat_message` is the original non-streaming turn (still used by
`/assistant/chat`): a turn that needs several tool calls is fully resolved
server-side before anything is returned.

`send_chat_message_stream` streams the model's own output live over SSE
(`/assistant/chat/stream`) using `stream_chat_completions`. A tool-calling
iteration's deltas are content-free (the model emits tool_calls, not visible
text) so nothing streams during tool dispatch - only a turn's final,
content-only answer is ever seen arriving live; the tool-calling loop itself
is otherwise identical to the non-streaming path. See docs/assistant.md.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.service import CredentialService
from app.db.session import Databases
from app.domain.bootstrap import ensure_default_assistant_config
from app.domain.enums import AssistantMessageRole, AssistantProvider
from app.domain.models import AssistantConfig, AssistantMessage, utcnow
from app.llm.client import LLMRequestError, call_chat_completions, stream_chat_completions
from app.llm.tools import READ_ONLY_TOOL_SCHEMAS, TOOL_SCHEMAS, ToolExecutionError, dispatch_tool_call
from app.llm.usage import record_usage
from app.logging_setup import get_logger
from app.prompts import load_prompt

logger = get_logger(__name__)

HISTORY_MESSAGE_LIMIT = 20

SYSTEM_PROMPT_BASE = load_prompt("assistant_base")
SYSTEM_PROMPT_READ_ONLY = SYSTEM_PROMPT_BASE + " " + load_prompt("assistant_read_only_suffix")
SYSTEM_PROMPT_FULL_ACCESS = SYSTEM_PROMPT_BASE + " " + load_prompt("assistant_full_access_suffix")


class AssistantService:
    def __init__(self, databases: Databases) -> None:
        self._databases = databases

    async def get_config(self, session: AsyncSession) -> AssistantConfig:
        return await ensure_default_assistant_config(session)

    async def update_config(self, session: AsyncSession, updates: dict[str, Any]) -> AssistantConfig:
        config = await self.get_config(session)
        for field, value in updates.items():
            setattr(config, field, value)
        await session.commit()
        await session.refresh(config)
        return config

    async def list_messages(self, session: AsyncSession, limit: int = 100) -> list[AssistantMessage]:
        result = await session.execute(
            select(AssistantMessage).order_by(AssistantMessage.ts.desc()).limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def clear_messages(self, session: AsyncSession) -> None:
        await session.execute(delete(AssistantMessage))
        await session.commit()

    async def _resolve_api_key(
        self,
        credentials_session: AsyncSession,
        credential_service: CredentialService,
        config: AssistantConfig,
    ) -> str | None:
        if config.provider != AssistantProvider.OPENROUTER:
            return None
        if config.credential_id is None:
            raise LLMRequestError("OpenRouter is configured but no API key credential is set")
        secret = await credential_service.get_decrypted(credentials_session, config.credential_id)
        api_key = secret.get("token")
        if not isinstance(api_key, str) or not api_key:
            raise LLMRequestError("Stored OpenRouter credential has no 'token' field")
        return api_key

    async def _recent_history(self, session: AsyncSession) -> list[dict[str, Any]]:
        messages = await self.list_messages(session, limit=HISTORY_MESSAGE_LIMIT)
        return [{"role": m.role.value, "content": m.content} for m in messages]

    async def send_chat_message(
        self,
        session: AsyncSession,
        credentials_session: AsyncSession,
        credential_service: CredentialService,
        user_text: str,
    ) -> AssistantMessage:
        config = await self.get_config(session)
        api_key = await self._resolve_api_key(credentials_session, credential_service, config)

        history = await self._recent_history(session)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT_FULL_ACCESS if config.full_access else SYSTEM_PROMPT_READ_ONLY,
            },
            *history,
            {"role": "user", "content": user_text},
        ]

        tool_calls_made: list[dict[str, Any]] = []
        final_text = ""

        for _ in range(config.max_tool_iterations):
            response = await call_chat_completions(
                base_url=config.base_url,
                api_key=api_key,
                model=config.model,
                messages=messages,
                tools=TOOL_SCHEMAS if config.full_access else READ_ONLY_TOOL_SCHEMAS,
                timeout=config.llm_timeout_seconds,
            )
            usage = response.get("usage") or {}
            await record_usage(
                self._databases,
                source="assistant",
                agent="chat",
                provider=config.provider.value,
                model=config.model,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
            )
            choice = response["choices"][0]["message"]
            requested = choice.get("tool_calls")
            if not requested:
                final_text = choice.get("content") or ""
                break

            messages.append(choice)
            for call in requested:
                name = call["function"]["name"]
                arguments: dict[str, Any] = {}
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                    result: Any = await dispatch_tool_call(
                        self._databases, name, arguments, full_access=config.full_access
                    )
                except (ToolExecutionError, json.JSONDecodeError) as exc:
                    result = {"error": str(exc)}
                tool_calls_made.append({"name": name, "arguments": arguments, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, default=str),
                    }
                )
        else:
            final_text = final_text or (
                f"Reached the limit of {config.max_tool_iterations} model calls for this turn without a "
                "final answer. Raise it under AI Mode > Settings > Chat assistant."
            )

        session.add(AssistantMessage(role=AssistantMessageRole.USER, content=user_text, ts=utcnow()))
        reply = AssistantMessage(
            role=AssistantMessageRole.ASSISTANT,
            content=final_text,
            tool_calls=tool_calls_made or None,
            ts=utcnow(),
        )
        session.add(reply)
        await session.commit()
        await session.refresh(reply)
        return reply

    async def send_chat_message_stream(
        self,
        session: AsyncSession,
        credentials_session: AsyncSession,
        credential_service: CredentialService,
        user_text: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yields `{"delta": str}` for each content token of the turn's final, content-only answer,
        then exactly one `{"message": {...}}` (the persisted AssistantMessage, same shape
        AssistantMessageRead.model_validate produces) - or, on an LLM failure, one `{"error": str}`
        with nothing persisted. See the module docstring for what does and doesn't stream."""
        config = await self.get_config(session)
        try:
            api_key = await self._resolve_api_key(credentials_session, credential_service, config)
        except LLMRequestError as exc:
            yield {"error": str(exc)}
            return

        history = await self._recent_history(session)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT_FULL_ACCESS if config.full_access else SYSTEM_PROMPT_READ_ONLY,
            },
            *history,
            {"role": "user", "content": user_text},
        ]

        tool_calls_made: list[dict[str, Any]] = []
        final_text = ""

        try:
            for _ in range(config.max_tool_iterations):
                content_parts: list[str] = []
                tool_call_parts: dict[int, dict[str, str]] = {}
                prompt_tokens = completion_tokens = 0

                async for chunk in stream_chat_completions(
                    base_url=config.base_url,
                    api_key=api_key,
                    model=config.model,
                    messages=messages,
                    tools=TOOL_SCHEMAS if config.full_access else READ_ONLY_TOOL_SCHEMAS,
                    timeout=config.llm_timeout_seconds,
                ):
                    usage = chunk.get("usage")
                    if usage:
                        prompt_tokens = int(usage.get("prompt_tokens") or 0)
                        completion_tokens = int(usage.get("completion_tokens") or 0)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                        yield {"delta": delta["content"]}
                    for tc in delta.get("tool_calls") or []:
                        empty_slot = {"id": "", "name": "", "arguments": ""}
                        slot = tool_call_parts.setdefault(tc.get("index", 0), empty_slot)
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]

                await record_usage(
                    self._databases,
                    source="assistant",
                    agent="chat",
                    provider=config.provider.value,
                    model=config.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )

                if not tool_call_parts:
                    final_text = "".join(content_parts)
                    break

                assembled: list[dict[str, Any]] = [
                    {
                        "id": slot["id"] or f"call_{idx}",
                        "function": {"name": slot["name"], "arguments": slot["arguments"]},
                    }
                    for idx, slot in sorted(tool_call_parts.items())
                ]
                messages.append({"role": "assistant", "content": None, "tool_calls": assembled})
                for call in assembled:
                    name = call["function"]["name"]
                    arguments: dict[str, Any] = {}
                    try:
                        arguments = json.loads(call["function"]["arguments"] or "{}")
                        result: Any = await dispatch_tool_call(
                            self._databases, name, arguments, full_access=config.full_access
                        )
                    except (ToolExecutionError, json.JSONDecodeError) as exc:
                        result = {"error": str(exc)}
                    tool_calls_made.append({"name": name, "arguments": arguments, "result": result})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result, default=str),
                        }
                    )
            else:
                final_text = final_text or (
                    f"Reached the limit of {config.max_tool_iterations} model calls for this turn without a "
                    "final answer. Raise it under AI Mode > Settings > Chat assistant."
                )
        except LLMRequestError as exc:
            yield {"error": str(exc)}
            return

        session.add(AssistantMessage(role=AssistantMessageRole.USER, content=user_text, ts=utcnow()))
        reply = AssistantMessage(
            role=AssistantMessageRole.ASSISTANT,
            content=final_text,
            tool_calls=tool_calls_made or None,
            ts=utcnow(),
        )
        session.add(reply)
        await session.commit()
        await session.refresh(reply)
        yield {
            "message": {
                "id": reply.id,
                "ts": reply.ts.isoformat(),
                "role": reply.role.value,
                "content": reply.content,
                "tool_calls": reply.tool_calls,
            }
        }
