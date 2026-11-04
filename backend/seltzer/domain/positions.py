"""Placing an item between two neighbours in an ordered list (one-row updates)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, select, true, update

from seltzer.domain.context import Ctx
from seltzer.ordering import REBALANCE_LENGTH, key_between, spread


async def place(
    ctx: Ctx,
    model: Any,
    scope: ColumnElement[bool],
    *,
    key_col: Any,
    item_key: Any,
    above: Any = None,
    below: Any = None,
    default: str = "top",
) -> str:
    """Return a position for `item_key` between `above` and `below` within `scope`.

    `above` and `below` are keys (ids) of neighbours as the client saw them;
    `above` wins when both are given. The new key always sits between two
    *adjacent* items, so it can never collide with an existing key, even if
    the list changed since the client read it. Neighbours outside the scope
    are ignored; with neither, the item goes to the top (or bottom).
    Rebalances the whole scope when keys grow long.
    """
    pos = model.position
    others = scope if item_key is None else (scope & (key_col != item_key))

    async def position_of(key: Any) -> str | None:
        if key is None or key == item_key:
            return None
        return await ctx.db.scalar(select(pos).where(scope, key_col == key))

    async def first(where: Any, descending: bool = False) -> str | None:
        order = pos.desc() if descending else pos
        return await ctx.db.scalar(select(pos).where(others, where).order_by(order).limit(1))

    lo = await position_of(above)
    hi = None if lo is not None else await position_of(below)
    if lo is not None:
        hi = await first(pos > lo)
    elif hi is not None:
        lo = await first(pos < hi, descending=True)
    elif default == "top":
        hi = await first(true())
    else:
        lo = await first(true(), descending=True)

    key = key_between(lo, hi)
    if len(key) > REBALANCE_LENGTH:
        key = await _rebalance(ctx, model, others, key_col, insert_after=lo)
    return key


async def _rebalance(
    ctx: Ctx, model: Any, others: ColumnElement[bool], key_col: Any, insert_after: str | None
) -> str:
    rows = list(
        await ctx.db.execute(select(key_col, model.position).where(others).order_by(model.position))
    )
    slot = 0 if insert_after is None else sum(1 for _, p in rows if p <= insert_after)
    keys = spread(len(rows) + 1)
    new_key = keys.pop(slot)
    for (item, _), k in zip(rows, keys, strict=True):
        await ctx.db.execute(
            update(model)
            .where(key_col == item)
            .values(position=k)
            .execution_options(synchronize_session=False)
        )
    return new_key
