"""knowledge.db is a fourth, independent SQLite file - same isolation pattern as credentials.db."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_databases
from app.knowledge.models import KnowledgeCollection


@pytest.mark.asyncio
async def test_knowledge_tables_are_isolated_in_their_own_file(client: AsyncClient) -> None:
    databases = get_databases()

    async with databases.knowledge_session_factory() as session:
        session.add(KnowledgeCollection(name="t", description=""))
        await session.commit()

    async with databases.knowledge_session_factory() as session:
        stmt = select(KnowledgeCollection).where(KnowledgeCollection.name == "t")
        row = (await session.execute(stmt)).scalar_one()
        assert row.name == "t"

    assert databases.knowledge_engine is not databases.app_engine
    assert databases.knowledge_engine is not databases.credentials_engine
