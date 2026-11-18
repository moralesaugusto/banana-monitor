import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.enums import CredentialType


class CredentialCreate(BaseModel):
    label: str
    credential_type: CredentialType
    secret: dict[str, Any]
    in_agent_pool: bool = False


class CredentialUpdate(BaseModel):
    """Either or both. A `secret` here replaces the whole stored secret (rotation) and stamps
    `rotated_at`; a `label`-only update does not count as a rotation."""

    label: str | None = None
    secret: dict[str, Any] | None = None
    in_agent_pool: bool | None = None


class CredentialRead(BaseModel):
    """Deliberately excludes ciphertext/secret fields - never add them here."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    credential_type: CredentialType
    created_at: datetime.datetime
    rotated_at: datetime.datetime | None
    last_used_at: datetime.datetime | None
    in_agent_pool: bool = False
    used_by: list[str] = []
    """What currently references this credential (integrations, agents, the agents' default LLM,
    the chat assistant, Telegram, a network auto-login binding) - set by the route, not a real
    column. Empty means nothing references it: safe to delete."""
