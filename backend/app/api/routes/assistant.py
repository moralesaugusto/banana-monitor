import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import AppSession, CredentialServiceDep, CredentialsSession
from app.api.schemas.ai_mode import VerifyResult
from app.api.schemas.assistant import (
    AssistantConfigRead,
    AssistantConfigUpdate,
    AssistantMessageRead,
    AssistantToolInfo,
    AssistantTools,
    ChatRequest,
    ChatResponse,
    ConnectionTest,
)
from app.credentials.service import CredentialNotFoundError
from app.db.session import get_databases
from app.domain.enums import AssistantProvider
from app.domain.models import AssistantConfig, AssistantMessage
from app.llm.client import LLMRequestError
from app.llm.connection_check import check_connection
from app.llm.service import AssistantService
from app.llm.tools import TOOL_SCHEMAS, WRITE_TOOL_NAMES

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/config", response_model=AssistantConfigRead)
async def get_config(session: AppSession) -> AssistantConfig:
    return await AssistantService(get_databases()).get_config(session)


@router.get("/tools", response_model=AssistantTools)
async def get_tools(session: AppSession) -> AssistantTools:
    """Every tool the chat assistant may call, and whether it's actually usable right now given
    AssistantConfig.full_access - the same WRITE_TOOL_NAMES allowlist dispatch_tool_call enforces
    (llm/tools.py), so this can't drift from what the assistant can really do."""
    config = await AssistantService(get_databases()).get_config(session)
    return AssistantTools(
        tools=[
            AssistantToolInfo(
                name=t["function"]["name"],
                description=t["function"]["description"],
                parameters=t["function"]["parameters"],
                write=t["function"]["name"] in WRITE_TOOL_NAMES,
                enabled=t["function"]["name"] not in WRITE_TOOL_NAMES or config.full_access,
            )
            for t in TOOL_SCHEMAS
        ]
    )


@router.put("/config", response_model=AssistantConfigRead)
async def update_config(
    payload: AssistantConfigUpdate,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> AssistantConfig:
    service = AssistantService(get_databases())
    current = await service.get_config(session)
    updates = payload.model_dump(exclude_unset=True)

    resulting_provider = updates.get("provider", current.provider)
    resulting_credential_id = updates.get("credential_id", current.credential_id)
    if resulting_provider == AssistantProvider.OPENROUTER:
        if resulting_credential_id is None:
            raise HTTPException(status_code=400, detail="OpenRouter requires an API key credential_id")
        try:
            await credential_service.get_decrypted(credentials_session, resulting_credential_id)
        except CredentialNotFoundError as exc:
            raise HTTPException(status_code=400, detail="credential_id does not exist") from exc

    return await service.update_config(session, updates)


@router.post("/test", response_model=VerifyResult)
async def test_config(
    payload: ConnectionTest,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> VerifyResult:
    """Tries the connection the way agents use it. The stored OpenRouter key stays a local variable."""
    service = AssistantService(get_databases())
    config = await service.get_config(session)
    provider = payload.provider or config.provider
    api_key = payload.api_key
    key_id = payload.credential_id or config.credential_id
    if provider == AssistantProvider.OPENROUTER and not api_key and key_id is not None:
        try:
            secret = await credential_service.get_decrypted(credentials_session, key_id)
        except CredentialNotFoundError:
            secret = {}
        api_key = secret.get("token") if isinstance(secret.get("token"), str) else None
    return await check_connection(
        provider,
        payload.base_url or config.base_url,
        payload.model or config.model,
        api_key,
        payload.timeout_seconds or config.llm_timeout_seconds,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> ChatResponse:
    service = AssistantService(get_databases())
    try:
        reply = await service.send_chat_message(
            session, credentials_session, credential_service, payload.message
        )
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc
    return ChatResponse(reply=AssistantMessageRead.model_validate(reply))


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> StreamingResponse:
    """SSE: `data: {"delta": "..."}` per content token of the turn's final answer, then one
    `data: {"message": {...}}`, or one `data: {"error": "..."}` on an LLM failure. See
    app.llm.service's module docstring for exactly what does and doesn't stream."""
    service = AssistantService(get_databases())

    async def events() -> AsyncIterator[str]:
        async for event in service.send_chat_message_stream(
            session, credentials_session, credential_service, payload.message
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/messages", response_model=list[AssistantMessageRead])
async def list_messages(session: AppSession, limit: int = 100) -> list[AssistantMessage]:
    return await AssistantService(get_databases()).list_messages(session, limit)


@router.delete("/messages", status_code=204)
async def clear_messages(session: AppSession) -> None:
    await AssistantService(get_databases()).clear_messages(session)
