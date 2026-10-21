from fastapi import APIRouter, HTTPException

from app.api.deps import AppSession, CredentialServiceDep, CredentialsSession
from app.api.schemas.ai_mode import VerifyResult
from app.api.schemas.assistant import (
    AssistantConfigRead,
    AssistantConfigUpdate,
    AssistantMessageRead,
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

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/config", response_model=AssistantConfigRead)
async def get_config(session: AppSession) -> AssistantConfig:
    return await AssistantService(get_databases()).get_config(session)


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


@router.get("/messages", response_model=list[AssistantMessageRead])
async def list_messages(session: AppSession, limit: int = 100) -> list[AssistantMessage]:
    return await AssistantService(get_databases()).list_messages(session, limit)


@router.delete("/messages", status_code=204)
async def clear_messages(session: AppSession) -> None:
    await AssistantService(get_databases()).clear_messages(session)
