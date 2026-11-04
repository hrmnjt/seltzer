"""Who can see and change what inside Seltzer.

Databricks decides who gets into the app (CAN USE). Inside it:
- all-access boards are visible to every Seltzer user;
- restricted boards to their access list, their creator, admins and owners;
- board settings, columns and access belong to the creator, admins and owners;
- drafts are visible only to their author.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, exists, or_, select, true

from seltzer.db.models import Board, BoardAccess, Card
from seltzer.domain.context import Ctx
from seltzer.domain.errors import Conflict, Forbidden, NotFound


def visible_boards(ctx: Ctx) -> ColumnElement[bool]:
    """A filter on Board for the boards the current user can see."""
    if ctx.user is None or ctx.is_admin:
        return true()
    has_access = exists().where(BoardAccess.board_id == Board.id, BoardAccess.user_id == ctx.me.id)
    return or_(Board.all_access, Board.created_by == ctx.me.id, has_access)


def visible_cards(ctx: Ctx) -> ColumnElement[bool]:
    """A filter on Card (joined to Board) for cards the current user can see."""
    if ctx.user is None:
        return Card.status == "published"
    return or_(Card.status == "published", Card.created_by == ctx.me.id)


def can_admin_board(ctx: Ctx, board: Board) -> bool:
    return ctx.is_admin or (ctx.user is not None and board.created_by == ctx.me.id)


async def can_see_board(ctx: Ctx, board: Board) -> bool:
    if ctx.user is None or ctx.is_admin or board.all_access or board.created_by == ctx.me.id:
        return True
    row = await ctx.db.scalar(
        select(BoardAccess.user_id).where(
            BoardAccess.board_id == board.id, BoardAccess.user_id == ctx.me.id
        )
    )
    return row is not None


async def get_board(
    ctx: Ctx, board_id: uuid.UUID, *, admin: bool = False, write: bool = False
) -> Board:
    board = await ctx.db.get(Board, board_id)
    if board is None or not await can_see_board(ctx, board):
        raise NotFound("No such board")
    if admin and not can_admin_board(ctx, board):
        raise Forbidden("Only the board's creator or an admin can change this")
    if (write or admin) and board.archived_at is not None and not admin:
        raise Conflict("This board is archived")
    return board


async def get_card(
    ctx: Ctx, number: int, *, write: bool = False, lock: bool = False
) -> tuple[Card, Board]:
    stmt = select(Card).where(Card.number == number)
    if lock:
        stmt = stmt.with_for_update()
    card = await ctx.db.scalar(stmt)
    if card is None:
        raise NotFound(f"No card #{number}")
    if card.status == "draft" and (ctx.user is None or card.created_by != ctx.me.id):
        raise NotFound(f"No card #{number}")
    board = await ctx.db.get(Board, card.board_id)
    assert board is not None
    if not await can_see_board(ctx, board):
        raise NotFound(f"No card #{number}")
    if write and board.archived_at is not None:
        raise Conflict("This card's board is archived")
    return card, board
