from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.crypto import get_secret_box
from app.credentials.service import CredentialNotFoundError, CredentialService
from app.db.session import get_databases


async def get_app_session() -> AsyncIterator[AsyncSession]:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        yield session


async def get_credentials_session() -> AsyncIterator[AsyncSession]:
    databases = get_databases()
    async with databases.credentials_session_factory() as session:
        yield session


async def get_metrics_session() -> AsyncIterator[AsyncSession]:
    databases = get_databases()
    async with databases.metrics_session_factory() as session:
        yield session


def get_credential_service() -> CredentialService:
    return CredentialService(get_secret_box())


AppSession = Annotated[AsyncSession, Depends(get_app_session)]
CredentialsSession = Annotated[AsyncSession, Depends(get_credentials_session)]
MetricsSession = Annotated[AsyncSession, Depends(get_metrics_session)]
CredentialServiceDep = Annotated[CredentialService, Depends(get_credential_service)]


async def require_credential(
    service: CredentialService, session: AsyncSession, credential_id: int | None
) -> None:
    """OpenRouter needs an API key credential that exists (its value is not read here)."""
    if credential_id is None:
        raise HTTPException(status_code=422, detail="OpenRouter needs an API key credential")
    try:
        await service.get_decrypted(session, credential_id)
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=422, detail="The API key credential does not exist") from exc
