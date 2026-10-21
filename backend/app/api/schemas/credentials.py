import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.enums import CredentialType


class CredentialCreate(BaseModel):
    label: str
    credential_type: CredentialType
    secret: dict[str, Any]


class CredentialRead(BaseModel):
    """Deliberately excludes ciphertext/secret fields - never add them here."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    credential_type: CredentialType
    created_at: datetime.datetime
    rotated_at: datetime.datetime | None
    last_used_at: datetime.datetime | None
