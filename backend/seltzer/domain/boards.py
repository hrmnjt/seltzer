"""Boards, their columns, access lists and watchers."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from seltzer.db.models import Board, BoardAccess, BoardWatch, Card, Column, User
from seltzer.domain.context import Ctx
from seltzer.domain.errors import Invalid, NotFound
from seltzer.domain.positions import place

# Our own palette of column colours; the frontend maps each name to theme tokens.
COLUMN_COLORS = (
    "gray",
    "red",
    "orange",
    "amber",
    "lime",
    "green",
    "teal",
    "cyan",
    "blue",
    "indigo",
    "violet",
    "pink",
)
MIN_PERIOD, MAX_PERIOD = 3, 365


def _name(name: str, what: str = "board") -> str:
    name = " ".join(name.split())
    if not name or len(name) > 120:
        raise Invalid(f"A {what} name needs 1 to 120 characters")
    return name


def _period(days: int | None) -> int | None:
    if days is not None and not MIN_PERIOD <= days <= MAX_PERIOD:
        raise Invalid(f"Auto-postpone periods run from {MIN_PERIOD} to {MAX_PERIOD} days")
    return days


def _color(color: str) -> str:
    if color not in COLUMN_COLORS:
        raise Invalid(f"Column colours are one of: {', '.join(COLUMN_COLORS)}")
    return color


async def create_board(
    ctx: Ctx,
    *,
    name: str,
    all_access: bool,
    auto_postpone_days: int | None,
    columns: list[tuple[str, str]],
) -> Board:
    board = Board(
        name=_name(name),
        all_access=all_access,
        auto_postpone_days=_period(auto_postpone_days),
        created_by=ctx.me.id,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(board)
    await ctx.db.flush()
    await set_watch(ctx, board, True)
    for col_name, color in columns:
        await add_column(ctx, board, name=col_name, color=color, position_hint="bottom")
    return board


async def update_board(ctx: Ctx, board: Board, changes: dict[str, Any]) -> Board:
    if "name" in changes and changes["name"] is not None:
        board.name = _name(changes["name"])
    if "all_access" in changes and changes["all_access"] is not None:
        board.all_access = bool(changes["all_access"])
    if "auto_postpone_days" in changes:
        board.auto_postpone_days = _period(changes["auto_postpone_days"])
    if "archived" in changes and changes["archived"] is not None:
        board.archived_at = ctx.now if changes["archived"] else None
    board.updated_at = ctx.now
    board.version += 1
    ctx._bumped.add(board.id)
    return board


async def set_access(ctx: Ctx, board: Board, user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    wanted = set(user_ids)
    known = (
        set(await ctx.db.scalars(select(User.id).where(User.id.in_(wanted)))) if wanted else set()
    )
    if missing := wanted - known:
        raise Invalid("Unknown people in the access list", missing=[str(m) for m in missing])
    await ctx.db.execute(delete(BoardAccess).where(BoardAccess.board_id == board.id))
    if wanted:
        await ctx.db.execute(
            pg_insert(BoardAccess),
            [{"board_id": board.id, "user_id": uid, "created_at": ctx.now} for uid in wanted],
        )
    await ctx.bump_board(board.id)
    return sorted(wanted)


async def get_access(ctx: Ctx, board: Board) -> list[uuid.UUID]:
    return list(
        await ctx.db.scalars(select(BoardAccess.user_id).where(BoardAccess.board_id == board.id))
    )


async def set_watch(ctx: Ctx, board: Board, watching: bool) -> None:
    if watching:
        await ctx.db.execute(
            pg_insert(BoardWatch)
            .values(board_id=board.id, user_id=ctx.me.id, created_at=ctx.now)
            .on_conflict_do_nothing()
        )
    else:
        await ctx.db.execute(
            delete(BoardWatch).where(
                BoardWatch.board_id == board.id, BoardWatch.user_id == ctx.me.id
            )
        )


async def add_column(
    ctx: Ctx,
    board: Board,
    *,
    name: str,
    color: str,
    above: uuid.UUID | None = None,
    below: uuid.UUID | None = None,
    position_hint: str = "bottom",
) -> Column:
    column = Column(
        board_id=board.id, name=_name(name, "column"), color=_color(color), position="V"
    )
    column.position = await place(
        ctx,
        Column,
        Column.board_id == board.id,
        key_col=Column.id,
        item_key=None,
        above=above,
        below=below,
        default=position_hint,
    )
    ctx.db.add(column)
    await ctx.db.flush()
    await ctx.bump_board(board.id)
    return column


async def get_column(ctx: Ctx, column_id: uuid.UUID) -> Column:
    column = await ctx.db.get(Column, column_id)
    if column is None:
        raise NotFound("No such column")
    return column


async def update_column(ctx: Ctx, column: Column, changes: dict[str, Any]) -> Column:
    if changes.get("name") is not None:
        column.name = _name(changes["name"], "column")
    if changes.get("color") is not None:
        column.color = _color(changes["color"])
    if changes.get("above") is not None or changes.get("below") is not None:
        column.position = await place(
            ctx,
            Column,
            Column.board_id == column.board_id,
            key_col=Column.id,
            item_key=column.id,
            above=changes.get("above"),
            below=changes.get("below"),
        )
    await ctx.bump_board(column.board_id)
    return column


async def delete_column(ctx: Ctx, column: Column) -> int:
    """Delete a column. Its open cards go back to Maybe?; done cards forget it.

    Returns how many open cards moved to Maybe?.
    """
    moved = await ctx.db.execute(
        update(Card)
        .where(Card.column_id == column.id, Card.state == "active")
        .values(column_id=None)
        .execution_options(synchronize_session=False)
    )
    await ctx.db.delete(column)
    await ctx.bump_board(column.board_id)
    return moved.rowcount or 0  # type: ignore[attr-defined]
