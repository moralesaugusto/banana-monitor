"""SQLite's foreign_keys pragma is per-connection, not persisted in the database file - setting it
once at startup (the old apply_pragmas behavior, via a NullPool connection that is immediately
discarded) has no effect on any later connection. Every one of the four databases needs it enabled
on every new connection, not just the first one ever opened."""

from httpx import AsyncClient

from app.db.session import get_databases


async def test_foreign_keys_are_enabled_on_every_connection_not_just_the_first(client: AsyncClient) -> None:
    databases = get_databases()
    for engine in (
        databases.app_engine,
        databases.metrics_engine,
        databases.credentials_engine,
        databases.knowledge_engine,
    ):
        for _ in range(2):  # NullPool: each connect() opens a brand new DBAPI connection
            async with engine.connect() as conn:
                result = await conn.exec_driver_sql("PRAGMA foreign_keys")
                assert result.scalar() == 1
