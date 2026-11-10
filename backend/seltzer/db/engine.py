"""Database engines and sessions.

On Databricks the app connects to Lakebase as its own service principal with
an OAuth token as the password. Tokens last an hour, so a fresh one is
fetched (and cached until shortly before expiry) whenever the pool opens a new
connection. Open connections stay valid after their token expires.
"""

from __future__ import annotations

import threading
import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from seltzer.config import Settings, get_settings

TOKEN_REFRESH_MARGIN_S = 10 * 60


class LakebaseTokens:
    """Caches the Lakebase OAuth token for one endpoint."""

    def __init__(self, endpoint_name: str) -> None:
        self.endpoint_name = endpoint_name
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        self._client: Any = None

    def get(self) -> str:
        with self._lock:
            if self._token is None or time.time() > self._expires_at - TOKEN_REFRESH_MARGIN_S:
                from databricks.sdk import WorkspaceClient

                if self._client is None:
                    self._client = WorkspaceClient()
                cred = self._client.postgres.generate_database_credential(
                    endpoint=self.endpoint_name
                )
                self._token = cred.token
                expires = cred.expire_time.ToDatetime().timestamp() if cred.expire_time else None
                self._expires_at = expires or time.time() + 3600
            assert self._token is not None
            return self._token


def database_url(settings: Settings, *, driver: str = "psycopg") -> URL:
    return URL.create(
        f"postgresql+{driver}",
        username=settings.pguser,
        password=settings.pgpassword,
        host=settings.pghost,
        port=settings.pgport,
        database=settings.pgdatabase,
        query={"sslmode": settings.pgsslmode, "application_name": "seltzer"},
    )


def _attach_token_provider(sync_engine: Engine, settings: Settings) -> None:
    if not settings.uses_lakebase_tokens:
        return
    assert settings.endpoint_name is not None
    tokens = LakebaseTokens(settings.endpoint_name)

    @event.listens_for(sync_engine, "do_connect")
    def _provide_token(dialect: Any, conn_rec: Any, cargs: Any, cparams: dict[str, Any]) -> None:
        cparams["password"] = tokens.get()


def make_async_engine(settings: Settings | None = None) -> AsyncEngine:
    settings = settings or get_settings()
    engine = create_async_engine(
        database_url(settings),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,  # Lakebase may scale to zero and drop idle connections
        pool_recycle=45 * 60,
    )
    _attach_token_provider(engine.sync_engine, settings)
    return engine


def make_sync_engine(settings: Settings | None = None) -> Engine:
    """Used by Alembic."""
    settings = settings or get_settings()
    engine = create_engine(database_url(settings), pool_pre_ping=True)
    _attach_token_provider(engine, settings)
    return engine


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
