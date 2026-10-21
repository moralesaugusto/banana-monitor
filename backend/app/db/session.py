from collections.abc import AsyncIterator
from functools import lru_cache

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
    return create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 30})


class Databases:
    """Owns the three independent SQLite engines: app, metrics, credentials."""

    def __init__(self, settings: Settings) -> None:
        self.app_engine = _make_engine(settings.app_db_url)
        self.metrics_engine = _make_engine(settings.metrics_db_url)
        self.credentials_engine = _make_engine(settings.credentials_db_url)

        self.app_session_factory = async_sessionmaker(self.app_engine, expire_on_commit=False)
        self.metrics_session_factory = async_sessionmaker(
            self.metrics_engine, expire_on_commit=False
        )
        self.credentials_session_factory = async_sessionmaker(
            self.credentials_engine, expire_on_commit=False
        )

    async def apply_pragmas(self) -> None:
        for engine in (self.app_engine, self.metrics_engine, self.credentials_engine):
            async with engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
                await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
                await conn.exec_driver_sql("PRAGMA busy_timeout=5000")
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    async def dispose(self) -> None:
        await self.app_engine.dispose()
        await self.metrics_engine.dispose()
        await self.credentials_engine.dispose()

    async def app_session(self) -> AsyncIterator[AsyncSession]:
        async with self.app_session_factory() as session:
            yield session

    async def metrics_session(self) -> AsyncIterator[AsyncSession]:
        async with self.metrics_session_factory() as session:
            yield session

    async def credentials_session(self) -> AsyncIterator[AsyncSession]:
        async with self.credentials_session_factory() as session:
            yield session


@lru_cache
def get_databases() -> Databases:
    return Databases(get_settings())
