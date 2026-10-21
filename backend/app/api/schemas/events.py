import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import EntityType, EventSeverity


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime.datetime
    source: str
    severity: EventSeverity
    category: str
    message: str
    related_entity_type: EntityType | None
    related_entity_id: int | None
