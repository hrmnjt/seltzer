"""/api/boards and /api/columns."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response

from seltzer.api.deps import get_ctx
from seltzer.api.schemas import (
    AccessIn,
    AccessOut,
    BoardIn,
    BoardPatch,
    BoardSnapshot,
    BoardSummary,
    CardIn,
    CardPage,
    CardResponse,
    ColumnIn,
    ColumnOut,
    ColumnPatch,
)
from seltzer.domain import boards as boards_domain
from seltzer.domain import cards as lifecycle
from seltzer.domain import queries
from seltzer.domain.context import Ctx
from seltzer.domain.permissions import get_board

router = APIRouter(tags=["boards"])


@router.get("/boards")
async def list_boards(
    include_archived: bool = False, ctx: Ctx = Depends(get_ctx)
) -> list[BoardSummary]:
    return await queries.list_boards(ctx, include_archived=include_archived)


@router.post("/boards", status_code=201)
async def create_board(body: BoardIn, ctx: Ctx = Depends(get_ctx)) -> BoardSummary:
    board = await boards_domain.create_board(
        ctx,
        name=body.name,
        all_access=body.all_access,
        auto_postpone_days=body.auto_postpone_days,
        columns=[(c.name, c.color) for c in body.columns],
    )
    [summary] = await queries.board_summaries(ctx, [board])
    await ctx.db.commit()
    return summary


@router.get(
    "/boards/{board_id}",
    response_model=BoardSnapshot,
    responses={204: {"description": "Unchanged since the version in `since`"}},
)
async def board_snapshot(
    board_id: uuid.UUID,
    since: int | None = Query(
        default=None, description="Return 204 if the board is still at this version"
    ),
    ctx: Ctx = Depends(get_ctx),
) -> BoardSnapshot | Response:
    board = await get_board(ctx, board_id)
    if since is not None and since == board.version:
        return Response(status_code=204)
    return await queries.snapshot(ctx, board)


@router.patch("/boards/{board_id}")
async def update_board(
    board_id: uuid.UUID, body: BoardPatch, ctx: Ctx = Depends(get_ctx)
) -> BoardSummary:
    board = await get_board(ctx, board_id, admin=True)
    await boards_domain.update_board(ctx, board, body.model_dump(exclude_unset=True))
    await ctx.db.flush()
    [summary] = await queries.board_summaries(ctx, [board])
    await ctx.db.commit()
    return summary


@router.get("/boards/{board_id}/access")
async def get_access(board_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> AccessOut:
    board = await get_board(ctx, board_id)
    return AccessOut(user_ids=await boards_domain.get_access(ctx, board))


@router.put("/boards/{board_id}/access")
async def set_access(board_id: uuid.UUID, body: AccessIn, ctx: Ctx = Depends(get_ctx)) -> AccessOut:
    board = await get_board(ctx, board_id, admin=True)
    ids = await boards_domain.set_access(ctx, board, body.user_ids)
    await ctx.db.commit()
    return AccessOut(user_ids=ids)


@router.put("/boards/{board_id}/watch", status_code=204)
async def watch_board(board_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    board = await get_board(ctx, board_id)
    await boards_domain.set_watch(ctx, board, True)
    await ctx.db.commit()
    return Response(status_code=204)


@router.delete("/boards/{board_id}/watch", status_code=204)
async def unwatch_board(board_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    board = await get_board(ctx, board_id)
    await boards_domain.set_watch(ctx, board, False)
    await ctx.db.commit()
    return Response(status_code=204)


@router.post("/boards/{board_id}/columns", status_code=201)
async def create_column(
    board_id: uuid.UUID, body: ColumnIn, ctx: Ctx = Depends(get_ctx)
) -> ColumnOut:
    board = await get_board(ctx, board_id, admin=True, write=True)
    column = await boards_domain.add_column(
        ctx,
        board,
        name=body.name,
        color=body.color,
        above=body.above,
        below=body.below,
        position_hint="bottom",
    )
    out = ColumnOut.model_validate(column)
    await ctx.db.commit()
    return out


@router.patch("/columns/{column_id}")
async def update_column(
    column_id: uuid.UUID, body: ColumnPatch, ctx: Ctx = Depends(get_ctx)
) -> ColumnOut:
    column = await boards_domain.get_column(ctx, column_id)
    await get_board(ctx, column.board_id, admin=True, write=True)
    await boards_domain.update_column(ctx, column, body.model_dump(exclude_unset=True))
    out = ColumnOut.model_validate(column)
    await ctx.db.commit()
    return out


@router.delete("/columns/{column_id}", status_code=204)
async def delete_column(column_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    column = await boards_domain.get_column(ctx, column_id)
    await get_board(ctx, column.board_id, admin=True, write=True)
    await boards_domain.delete_column(ctx, column)
    await ctx.db.commit()
    return Response(status_code=204)


@router.get("/boards/{board_id}/cards")
async def list_cards(
    board_id: uuid.UUID,
    view: queries.View = "open",
    tag: uuid.UUID | None = None,
    assignee: uuid.UUID | None = None,
    sort: queries.Sort | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    ctx: Ctx = Depends(get_ctx),
) -> CardPage:
    board = await get_board(ctx, board_id)
    return await queries.list_cards(
        ctx,
        board,
        view=view,
        tag_id=tag,
        assignee_id=assignee,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )


@router.post("/boards/{board_id}/cards", status_code=201)
async def create_card(
    board_id: uuid.UUID, body: CardIn, ctx: Ctx = Depends(get_ctx)
) -> CardResponse:
    board = await get_board(ctx, board_id, write=True)
    card = await lifecycle.create(
        ctx, board, title=body.title, description=body.description, draft=body.draft
    )
    tile, users = await queries.card_response(ctx, card)
    await ctx.db.commit()
    return CardResponse(card=tile, users=users)
