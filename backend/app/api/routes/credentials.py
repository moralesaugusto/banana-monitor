from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import AppSession, CredentialServiceDep, CredentialsSession
from app.api.schemas.credentials import CredentialCreate, CredentialRead, CredentialUpdate
from app.credentials.models import Credential
from app.credentials.service import CredentialNotFoundError
from app.domain.bootstrap import ensure_default_ai_mode_settings
from app.domain.models import AiAgent, AssistantConfig, Integration, NetworkCredentialBinding, TelegramConfig

router = APIRouter(prefix="/credentials", tags=["credentials"])


async def _credential_users(app_session: AppSession, credential_id: int) -> list[str]:
    """Everything that references this credential by id - the single source of truth for both the
    "used by" list on GET and the delete-blocking check below. Keep every credential_id column in
    domain/models.py represented here; each was missed here once already (AiAgent's and
    AiModeSettings' were added after the others and both got left out of the original delete
    check - a credential actually in use by either could be deleted with no warning)."""
    users: list[str] = []
    in_use = Integration.credential_id == credential_id
    names = await app_session.scalars(select(Integration.name).where(in_use))
    users.extend(f"integration {name}" for name in names)
    bound = NetworkCredentialBinding.credential_id == credential_id
    if await app_session.scalar(select(NetworkCredentialBinding.id).where(bound)):
        users.append("a network auto-login binding")
    assistant = AssistantConfig.credential_id == credential_id
    if await app_session.scalar(select(AssistantConfig.id).where(assistant)):
        users.append("the chat assistant")
    telegram = TelegramConfig.credential_id == credential_id
    if await app_session.scalar(select(TelegramConfig.id).where(telegram)):
        users.append("Telegram")
    settings = await ensure_default_ai_mode_settings(app_session)
    if settings.llm_credential_id == credential_id:
        users.append("the agents' default LLM")
    agent_names = await app_session.scalars(
        select(AiAgent.name).where(AiAgent.credential_id == credential_id)
    )
    users.extend(f"agent {name}" for name in agent_names)
    fallback_names = await app_session.scalars(
        select(AiAgent.name).where(AiAgent.fallback_credential_id == credential_id)
    )
    users.extend(f"agent {name} (fallback key)" for name in fallback_names)
    if settings.knowledge_embedding_credential_id == credential_id:
        users.append("the knowledge base embeddings")
    return users


@router.get("", response_model=list[CredentialRead])
async def list_credentials(
    session: CredentialsSession, service: CredentialServiceDep, app_session: AppSession
) -> list[CredentialRead]:
    credentials = await service.list(session)
    reads = [CredentialRead.model_validate(c) for c in credentials]
    for read in reads:
        read.used_by = await _credential_users(app_session, read.id)
    return reads


@router.post("", response_model=CredentialRead, status_code=201)
async def create_credential(
    payload: CredentialCreate, session: CredentialsSession, service: CredentialServiceDep
) -> Credential:
    return await service.create(
        session, payload.label, payload.credential_type, payload.secret, payload.in_agent_pool
    )


@router.patch("/{credential_id}", response_model=CredentialRead)
async def update_credential(
    credential_id: int,
    payload: CredentialUpdate,
    session: CredentialsSession,
    service: CredentialServiceDep,
    app_session: AppSession,
) -> CredentialRead:
    try:
        credential = await service.update(
            session,
            credential_id,
            label=payload.label,
            secret=payload.secret,
            in_agent_pool=payload.in_agent_pool,
        )
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Credential not found") from exc
    read = CredentialRead.model_validate(credential)
    read.used_by = await _credential_users(app_session, read.id)
    return read


@router.delete("/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: int,
    session: CredentialsSession,
    service: CredentialServiceDep,
    app_session: AppSession,
) -> None:
    users = await _credential_users(app_session, credential_id)
    if users:
        raise HTTPException(
            status_code=409,
            detail=f"Credential is still used by {', '.join(users)}. Change or remove those first.",
        )
    try:
        await service.delete(session, credential_id)
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Credential not found") from exc
