import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AssistantMessageRole, AssistantProvider


class AssistantConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: AssistantProvider
    base_url: str
    model: str
    credential_id: int | None
    max_tool_iterations: int
    llm_timeout_seconds: float
    full_access: bool
    """False (default): read tools only. True ("god mode"): every curated tool, including safe
    writes. Enforced server-side either way - see AssistantConfig.full_access."""


class AssistantConfigUpdate(BaseModel):
    provider: AssistantProvider | None = None
    base_url: str | None = None
    model: str | None = None
    credential_id: int | None = None
    max_tool_iterations: int | None = Field(default=None, ge=1, le=40)
    llm_timeout_seconds: float | None = Field(default=None, ge=10, le=1800)
    full_access: bool | None = None


class ConnectionTest(BaseModel):
    """Values to test, usually the unsaved form. Anything left out comes from the saved configuration;
    `api_key` is used for this test only and never stored."""

    provider: AssistantProvider | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    credential_id: int | None = None
    """A stored key to test with when `api_key` is not typed; defaults to the chat assistant's."""
    timeout_seconds: float | None = Field(default=None, ge=10, le=1800)


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: Any


class AssistantMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime.datetime
    role: AssistantMessageRole
    content: str
    tool_calls: list[ToolCallRecord] | None


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: AssistantMessageRead
