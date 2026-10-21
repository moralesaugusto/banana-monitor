"""Chat-turn orchestration: one user message -> a bounded tool-calling loop
against the configured LLM -> one persisted assistant reply.

Non-streaming by design (v1): a turn that needs several tool calls is fully
resolved server-side before anything is returned. Streaming interacting with
tool-call parsing is real added complexity, deliberately deferred - see
docs/assistant.md.
"""

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.service import CredentialService
from app.db.session import Databases
from app.domain.bootstrap import ensure_default_assistant_config
from app.domain.enums import AssistantMessageRole, AssistantProvider
from app.domain.models import AssistantConfig, AssistantMessage, utcnow
from app.llm.client import LLMRequestError, call_chat_completions
from app.llm.tools import READ_ONLY_TOOL_SCHEMAS, TOOL_SCHEMAS, ToolExecutionError, dispatch_tool_call
from app.llm.usage import record_usage
from app.logging_setup import get_logger

logger = get_logger(__name__)

HISTORY_MESSAGE_LIMIT = 20

SYSTEM_PROMPT_BASE = (
    "You are an assistant embedded in a LAN monitoring platform. You can read "
    "current device/service/alert/discovery state. You cannot delete anything "
    "and cannot touch credentials, integration configuration or any system/"
    "platform setting - if asked, say those must be changed manually in the UI. "
    "Be concise."
)
SYSTEM_PROMPT_READ_ONLY = SYSTEM_PROMPT_BASE + (
    " You are currently in read-only mode: you have no write tools at all, only "
    "read ones. If asked to change something, say that full access (god mode) "
    "must be turned on first, under AI Mode > Settings > Chat assistant."
)
SYSTEM_PROMPT_FULL_ACCESS = SYSTEM_PROMPT_BASE + (
    " Full access is on: you may also perform the curated safe write actions "
    "your tools expose (accept/ignore a discovery candidate, create or update a "
    "service, update a device, trigger a scan, enable/disable an alert rule)."
)


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
