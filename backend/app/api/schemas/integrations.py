import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import IntegrationStatus


class IntegrationTypeInfo(BaseModel):
    type_key: str
    display_name: str
    config_schema: dict[str, Any]
    credential_schema: dict[str, Any] | None


class IntegrationBase(BaseModel):
    integration_type: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=100)
    config: dict[str, Any] = {}
    credential_id: int | None = None
    enabled: bool = True


class IntegrationCreate(IntegrationBase):
    pass


class IntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: dict[str, Any] | None = None
    credential_id: int | None = None
    enabled: bool | None = None


class IntegrationRead(IntegrationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: IntegrationStatus
    last_run_at: datetime.datetime | None
    last_error: str | None
