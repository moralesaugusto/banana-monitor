from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings


def _make_engine(url: str) -> AsyncEngine:
    # SQLite allows one writer at a time; wait up to 30 s for the lock (a VACUUM or a big cleanup can hold
    # it for several seconds) before failing, instead of the 5 s default.
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 30})

    # foreign_keys is a per-connection SQLite setting, not persisted in the database file - unlike
    # journal_mode, setting it once in apply_pragmas() below only ever affected that one throwaway
    # connection. NullPool opens a brand new DBAPI connection on every checkout, so this has to run
    # on each one via the standard SQLAlchemy "connect" pool event, not once at startup.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


class Databases:
    """Owns the four independent SQLite engines: app, metrics, credentials, knowledge."""

    def __init__(self, settings: Settings) -> None:
        self.app_engine = _make_engine(settings.app_db_url)
        self.metrics_engine = _make_engine(settings.metrics_db_url)
        self.credentials_engine = _make_engine(settings.credentials_db_url)
        self.knowledge_engine = _make_engine(settings.knowledge_db_url)

        self.app_session_factory = async_sessionmaker(self.app_engine, expire_on_commit=False)
        self.metrics_session_factory = async_sessionmaker(
            self.metrics_engine, expire_on_commit=False
        )
        self.credentials_session_factory = async_sessionmaker(
            self.credentials_engine, expire_on_commit=False
        )
        self.knowledge_session_factory = async_sessionmaker(
            self.knowledge_engine, expire_on_commit=False
        )

    async def apply_pragmas(self) -> None:
        for engine in (self.app_engine, self.metrics_engine, self.credentials_engine, self.knowledge_engine):
            async with engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
                await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
                await conn.exec_driver_sql("PRAGMA busy_timeout=5000")

    async def dispose(self) -> None:
        await self.app_engine.dispose()
        await self.metrics_engine.dispose()
        await self.credentials_engine.dispose()
        await self.knowledge_engine.dispose()

    async def app_session(self) -> AsyncIterator[AsyncSession]:
        async with self.app_session_factory() as session:
            yield session

    async def metrics_session(self) -> AsyncIterator[AsyncSession]:
        async with self.metrics_session_factory() as session:
            yield session

    async def credentials_session(self) -> AsyncIterator[AsyncSession]:
        async with self.credentials_session_factory() as session:
            yield session

    async def knowledge_session(self) -> AsyncIterator[AsyncSession]:
        async with self.knowledge_session_factory() as session:
            yield session


@lru_cache
def get_databases() -> Databases:
    return Databases(get_settings())
