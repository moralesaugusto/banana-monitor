import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.crypto import SecretBox
from app.credentials.models import Credential
from app.domain.enums import CredentialType


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class CredentialNotFoundError(LookupError):
    pass


class CredentialService:
    def __init__(self, secret_box: SecretBox) -> None:
        self._secret_box = secret_box

    async def create(
        self,
        session: AsyncSession,
        label: str,
        credential_type: CredentialType,
        secret: dict[str, Any],
        in_agent_pool: bool = False,
    ) -> Credential:
        credential = Credential(
            label=label,
            credential_type=credential_type,
            ciphertext=self._secret_box.encrypt(secret),
            in_agent_pool=in_agent_pool,
        )
        session.add(credential)
        await session.commit()
        await session.refresh(credential)
        return credential

    async def list(self, session: AsyncSession) -> list[Credential]:
        result = await session.execute(select(Credential).order_by(Credential.label))
        return list(result.scalars().all())

    async def get_decrypted(self, session: AsyncSession, credential_id: int) -> dict[str, Any]:
        credential = await session.get(Credential, credential_id)
        if credential is None:
            raise CredentialNotFoundError(f"Credential {credential_id} not found")
        credential.last_used_at = utcnow()
        await session.commit()
        return self._secret_box.decrypt(credential.ciphertext)

    async def update(
        self,
        session: AsyncSession,
        credential_id: int,
        *,
        label: str | None = None,
        secret: dict[str, Any] | None = None,
        in_agent_pool: bool | None = None,
    ) -> Credential:
        credential = await session.get(Credential, credential_id)
        if credential is None:
            raise CredentialNotFoundError(f"Credential {credential_id} not found")
        if label is not None:
            credential.label = label
        if in_agent_pool is not None:
            credential.in_agent_pool = in_agent_pool
        if secret is not None:
            credential.ciphertext = self._secret_box.encrypt(secret)
            credential.rotated_at = utcnow()
        await session.commit()
        await session.refresh(credential)
        return credential

    async def delete(self, session: AsyncSession, credential_id: int) -> None:
        credential = await session.get(Credential, credential_id)
        if credential is None:
            raise CredentialNotFoundError(f"Credential {credential_id} not found")
        await session.delete(credential)
        await session.commit()
