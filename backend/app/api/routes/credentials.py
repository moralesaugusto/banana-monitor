from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import AppSession, CredentialServiceDep, CredentialsSession
from app.api.schemas.credentials import CredentialCreate, CredentialRead
from app.credentials.models import Credential
from app.credentials.service import CredentialNotFoundError
from app.domain.models import AssistantConfig, Integration, NetworkCredentialBinding

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get("", response_model=list[CredentialRead])
async def list_credentials(session: CredentialsSession, service: CredentialServiceDep) -> list[Credential]:
    return await service.list(session)


@router.post("", response_model=CredentialRead, status_code=201)
async def create_credential(
    payload: CredentialCreate, session: CredentialsSession, service: CredentialServiceDep
) -> Credential:
    return await service.create(session, payload.label, payload.credential_type, payload.secret)


@router.delete("/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: int,
    session: CredentialsSession,
    service: CredentialServiceDep,
    app_session: AppSession,
) -> None:
    in_use = Integration.credential_id == credential_id
    names = await app_session.scalars(select(Integration.name).where(in_use))
    users = [f"integration {name}" for name in names]
    bound = NetworkCredentialBinding.credential_id == credential_id
    if await app_session.scalar(select(NetworkCredentialBinding.id).where(bound)):
        users.append("a network auto-login binding")
    assistant = AssistantConfig.credential_id == credential_id
    if await app_session.scalar(select(AssistantConfig.id).where(assistant)):
        users.append("the chat assistant")
    if users:
        raise HTTPException(
            status_code=409,
            detail=f"Credential is still used by {', '.join(users)}. Change or remove those first.",
        )
    try:
        await service.delete(session, credential_id)
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Credential not found") from exc
