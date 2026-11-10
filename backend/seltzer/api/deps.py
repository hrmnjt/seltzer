"""Request-scoped dependencies: the database session and the signed-in user."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from seltzer.domain.context import Ctx
from seltzer.files import FileStore
from seltzer.identity import identity_from_headers, resolve_user


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.sessionmaker() as session:
        yield session


async def get_ctx(request: Request, db: AsyncSession = Depends(get_db)) -> Ctx:
    settings = request.app.state.settings
    ctx = Ctx(db=db, user=None, settings=settings)
    identity = identity_from_headers(request.headers, settings)
    await resolve_user(ctx, identity, request.app.state.directory)
    return ctx


def get_store(request: Request) -> FileStore:
    return request.app.state.store  # type: ignore[no-any-return]
