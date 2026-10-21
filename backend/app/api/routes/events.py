from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import AppSession
from app.api.schemas.events import EventRead
from app.domain.models import Event

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventRead])
async def list_events(session: AppSession, limit: int = 100) -> list[Event]:
    result = await session.execute(select(Event).order_by(Event.ts.desc()).limit(limit))
    return list(result.scalars().all())
