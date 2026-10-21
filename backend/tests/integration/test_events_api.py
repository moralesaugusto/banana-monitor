import datetime

import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.domain.models import Event


@pytest.mark.asyncio
async def test_list_events_ordered_newest_first(client: AsyncClient) -> None:
    now = datetime.datetime.now(datetime.UTC)
    databases = get_databases()
    async with databases.app_session_factory() as session:
        earlier = now - datetime.timedelta(seconds=10)
        session.add(Event(source="test", category="info", message="first", ts=earlier))
        session.add(Event(source="test", category="info", message="second", ts=now))
        await session.commit()

    response = await client.get("/api/events")
    assert response.status_code == 200
    messages = [e["message"] for e in response.json()]
    assert messages == ["second", "first"]
