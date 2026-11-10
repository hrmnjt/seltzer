"""/api/events, /api/notifications and /api/search."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import update

from seltzer.api.deps import get_ctx
from seltzer.api.schemas import EventPage, NotificationPage, ReadIn, SearchResults
from seltzer.db.models import Notification
from seltzer.domain import queries
from seltzer.domain.context import Ctx
from seltzer.domain.permissions import get_board

router = APIRouter(tags=["activity"])


@router.get("/events")
async def timeline(
    board: uuid.UUID | None = None,
    before: uuid.UUID | None = Query(default=None, description="Event id cursor"),
    limit: int = Query(default=50, ge=1, le=200),
    ctx: Ctx = Depends(get_ctx),
) -> EventPage:
    if board is not None:
        await get_board(ctx, board)
    return await queries.timeline(ctx, board_id=board, before=before, limit=limit)


@router.get("/notifications")
async def notifications(
    before: uuid.UUID | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    ctx: Ctx = Depends(get_ctx),
) -> NotificationPage:
    return await queries.notifications(ctx, before=before, limit=limit)


@router.post("/notifications/read", status_code=204)
async def mark_read(body: ReadIn, ctx: Ctx = Depends(get_ctx)) -> Response:
    stmt = (
        update(Notification)
        .where(Notification.user_id == ctx.me.id, Notification.read_at.is_(None))
        .values(read_at=ctx.now)
    )
    if body.card_ids is not None:
        stmt = stmt.where(Notification.card_id.in_(body.card_ids))
    await ctx.db.execute(stmt)
    await ctx.db.commit()
    return Response(status_code=204)


@router.get("/search")
async def search(
    q: str = Query(min_length=1, max_length=200),
    board: uuid.UUID | None = None,
    ctx: Ctx = Depends(get_ctx),
) -> SearchResults:
    return await queries.search(ctx, q, board_id=board)
