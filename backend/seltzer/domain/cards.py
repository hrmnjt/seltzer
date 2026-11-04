"""The card lifecycle.

States: Draft -> Maybe? (active, no column) -> a column (active) -> Done.
Postponing (by hand or after inactivity) sends an open card to Not Now and
clears its column; resuming returns it to Maybe?. Closing keeps the column, so
reopening puts the card back where it was. Golden is a flag, not a state.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from seltzer import richtext
from seltzer.db.models import Assignment, Attachment, Board, Card, CardTag, Column, Tag, User
from seltzer.domain import activity
from seltzer.domain.context import Ctx
from seltzer.domain.errors import Conflict, Forbidden, Invalid, NotFound
from seltzer.domain.permissions import can_admin_board, can_see_board, get_board
from seltzer.domain.positions import place

MAX_TITLE = 300


def _clean_title(title: str) -> str:
    title = " ".join(title.split())
    if not title:
        raise Invalid("A card needs a title")
    if len(title) > MAX_TITLE:
        raise Invalid(f"Titles are limited to {MAX_TITLE} characters")
    return title


def _check_description(doc: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    if doc is None:
        return None, ""
    try:
        richtext.validate(doc)
    except richtext.RichTextError as exc:
        raise Invalid(str(exc)) from exc
    return doc, richtext.plain_text(doc)


def lane(card: Card, column_id: uuid.UUID | None) -> Any:
    """The ordered list a card sits in: Maybe? (no column) or one column."""
    base = and_(Card.board_id == card.board_id, Card.status == "published", Card.state == "active")
    return base & (Card.column_id.is_(None) if column_id is None else Card.column_id == column_id)


async def _position(
    ctx: Ctx, card: Card, column_id: uuid.UUID | None, above: Any = None, below: Any = None
) -> str:
    return await place(
        ctx,
        Card,
        lane(card, column_id),
        key_col=Card.id,
        item_key=card.id,
        above=above,
        below=below,
    )


def _set_state(ctx: Ctx, card: Card, state: str, *, auto: bool = False) -> None:
    card.state = state
    card.state_changed_at = ctx.now
    card.state_changed_by = None if auto else ctx.me.id
    card.auto_postponed = auto


async def create(
    ctx: Ctx, board: Board, *, title: str, description: dict[str, Any] | None, draft: bool
) -> Card:
    doc, text = _check_description(description)
    card = Card(
        board_id=board.id,
        title=_clean_title(title),
        description=doc,
        description_text=text,
        status="draft" if draft else "published",
        state="active",
        created_by=ctx.me.id,
        last_active_at=ctx.now,
        position="V",
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(card)
    await ctx.db.flush()
    await activity.watch(ctx, card, ctx.me.id)
    if not draft:
        await _publish(ctx, card, mentions=richtext.mentioned_user_ids(doc))
    await ctx.db.refresh(card, ["number"])
    return card


async def _publish(ctx: Ctx, card: Card, mentions: set[uuid.UUID]) -> None:
    card.status = "published"
    card.published_at = ctx.now
    card.column_id = None
    card.position = await _position(ctx, card, None)
    await activity.record(ctx, "published", board_id=card.board_id, card=card, mentions=mentions)


async def publish(ctx: Ctx, card: Card) -> Card:
    if card.status != "draft":
        raise Conflict("This card is already published")
    await _publish(ctx, card, mentions=richtext.mentioned_user_ids(card.description))
    return card


async def triage(
    ctx: Ctx, card: Card, column_id: uuid.UUID, *, above: Any = None, below: Any = None
) -> Card:
    """Place a card in a column, or move it within or between columns.

    Works from Not Now and Done too: the card resumes or reopens on the way.
    """
    _require_published(card)
    column = await ctx.db.get(Column, column_id)
    if column is None or column.board_id != card.board_id:
        raise NotFound("No such column on this board")
    previous = card.column_id
    if card.state == "not_now":
        await _resume(ctx, card, place_in_maybe=False)
        previous = None
    elif card.state == "done":
        _set_state(ctx, card, "active")
        await activity.record(ctx, "reopened", board_id=card.board_id, card=card)
    card.position = await _position(ctx, card, column.id, above, below)
    card.column_id = column.id
    if previous is None:
        await activity.record(
            ctx,
            "triaged",
            board_id=card.board_id,
            card=card,
            details={"column_id": str(column.id), "column": column.name},
        )
    elif previous != column.id:
        old = await ctx.db.get(Column, previous)
        await activity.record(
            ctx,
            "moved",
            board_id=card.board_id,
            card=card,
            details={
                "from_column_id": str(previous),
                "from_column": old.name if old else None,
                "column_id": str(column.id),
                "column": column.name,
            },
        )
    else:
        await ctx.bump_board(card.board_id)  # a reorder: no stamp, but pollers refresh
    return card


async def reorder_in_maybe(ctx: Ctx, card: Card, *, above: Any = None, below: Any = None) -> Card:
    if card.state != "active" or card.column_id is not None:
        raise Conflict("Only cards in Maybe? can be reordered there")
    card.position = await _position(ctx, card, None, above, below)
    await ctx.bump_board(card.board_id)
    return card


async def untriage(ctx: Ctx, card: Card, *, above: Any = None, below: Any = None) -> Card:
    _require_published(card)
    if card.state != "active" or card.column_id is None:
        raise Conflict("Only cards in a column can go back to Maybe?", current=card.state)
    old = await ctx.db.get(Column, card.column_id)
    card.position = await _position(ctx, card, None, above, below)
    card.column_id = None
    await activity.record(
        ctx,
        "sent_back_to_triage",
        board_id=card.board_id,
        card=card,
        details={"from_column": old.name if old else None},
    )
    return card


async def postpone(ctx: Ctx, card: Card, *, auto: bool = False) -> Card:
    _require_published(card)
    if card.state != "active":
        raise Conflict("Only open cards can be postponed", current=card.state)
    old_column = card.column_id
    _set_state(ctx, card, "not_now", auto=auto)
    card.column_id = None
    await activity.record(
        ctx,
        "auto_postponed" if auto else "postponed",
        board_id=card.board_id,
        card=card,
        details={"from_column_id": str(old_column) if old_column else None},
    )
    return card


async def _resume(ctx: Ctx, card: Card, *, place_in_maybe: bool = True) -> None:
    _set_state(ctx, card, "active")
    card.column_id = None
    if place_in_maybe:
        card.position = await _position(ctx, card, None)
    await activity.record(ctx, "resumed", board_id=card.board_id, card=card)


async def resume(ctx: Ctx, card: Card) -> Card:
    _require_published(card)
    if card.state != "not_now":
        raise Conflict("Only cards in Not Now can be resumed", current=card.state)
    await _resume(ctx, card)
    return card


async def close(ctx: Ctx, card: Card) -> Card:
    _require_published(card)
    if card.state == "done":
        raise Conflict("This card is already done", current=card.state)
    _set_state(ctx, card, "done")
    await activity.record(ctx, "closed", board_id=card.board_id, card=card)
    return card


async def reopen(ctx: Ctx, card: Card) -> Card:
    _require_published(card)
    if card.state != "done":
        raise Conflict("Only done cards can be reopened", current=card.state)
    _set_state(ctx, card, "active")
    # The column was kept on close; if it was deleted since, the card lands in Maybe?.
    card.position = await _position(ctx, card, card.column_id)
    await activity.record(ctx, "reopened", board_id=card.board_id, card=card)
    return card


async def set_golden(ctx: Ctx, card: Card, golden: bool) -> Card:
    _require_published(card)
    if golden == (card.golden_at is not None):
        return card
    card.golden_at = ctx.now if golden else None
    await activity.record(
        ctx, "gilded" if golden else "ungilded", board_id=card.board_id, card=card
    )
    return card


async def edit(
    ctx: Ctx,
    card: Card,
    *,
    fields: set[str],
    title: str | None = None,
    description: dict[str, Any] | None = None,
    board_id: uuid.UUID | None = None,
    version: int | None = None,
) -> Card:
    if version is not None and version != card.version:
        raise Conflict("This card changed since you opened it", current_version=card.version)
    changed = False
    if "title" in fields and title is not None:
        new_title = _clean_title(title)
        if new_title != card.title:
            old = card.title
            card.title = new_title
            changed = True
            if card.status == "published":
                await activity.record(
                    ctx,
                    "title_changed",
                    board_id=card.board_id,
                    card=card,
                    details={"from": old, "to": new_title},
                )
    if "description" in fields:
        doc, text = _check_description(description)
        if doc != card.description:
            before = richtext.mentioned_user_ids(card.description)
            card.description = doc
            card.description_text = text
            changed = True
            if card.status == "published":
                newly_mentioned = richtext.mentioned_user_ids(doc) - before
                await activity.record(
                    ctx,
                    "description_changed",
                    board_id=card.board_id,
                    card=card,
                    mentions=newly_mentioned,
                )
    if "board_id" in fields and board_id is not None and board_id != card.board_id:
        await _change_board(ctx, card, board_id)
        changed = True
    if changed:
        card.version += 1
        card.updated_at = ctx.now
    return card


async def _change_board(ctx: Ctx, card: Card, board_id: uuid.UUID) -> None:
    source = await ctx.db.get(Board, card.board_id)
    target = await get_board(ctx, board_id, write=True)
    assert source is not None
    await ctx.bump_board(source.id)
    card.board_id = target.id
    card.column_id = None
    if card.status == "published" and card.state == "active":
        card.position = await _position(ctx, card, None)
    if card.status == "published":
        await activity.record(
            ctx,
            "board_changed",
            board_id=target.id,
            card=card,
            details={"from_board_id": str(source.id), "from_board": source.name},
        )


async def assign(ctx: Ctx, card: Card, user_id: uuid.UUID) -> Card:
    user = await ctx.db.get(User, user_id)
    if user is None or not user.active:
        raise NotFound("No such person")
    board = await ctx.db.get(Board, card.board_id)
    assert board is not None
    if not await can_see_board(Ctx(ctx.db, user, ctx.settings, ctx.now), board):
        raise Invalid(f"{user.display_name} can't see this board")
    result = await ctx.db.execute(
        pg_insert(Assignment)
        .values(card_id=card.id, user_id=user.id, assigned_by=ctx.me.id, created_at=ctx.now)
        .on_conflict_do_nothing()
    )
    if result.rowcount and card.status == "published":  # type: ignore[attr-defined]
        await activity.record(
            ctx,
            "assigned",
            board_id=card.board_id,
            card=card,
            details={"user_id": str(user.id), "name": user.display_name},
            assignee=user.id,
        )
    return card


async def unassign(ctx: Ctx, card: Card, user_id: uuid.UUID) -> Card:
    result = await ctx.db.execute(
        delete(Assignment).where(Assignment.card_id == card.id, Assignment.user_id == user_id)
    )
    if result.rowcount and card.status == "published":  # type: ignore[attr-defined]
        user = await ctx.db.get(User, user_id)
        await activity.record(
            ctx,
            "unassigned",
            board_id=card.board_id,
            card=card,
            details={"user_id": str(user_id), "name": user.display_name if user else None},
        )
    return card


async def tag(ctx: Ctx, card: Card, tag_id: uuid.UUID) -> Card:
    tag = await ctx.db.get(Tag, tag_id)
    if tag is None:
        raise NotFound("No such tag")
    result = await ctx.db.execute(
        pg_insert(CardTag).values(card_id=card.id, tag_id=tag.id).on_conflict_do_nothing()
    )
    if result.rowcount and card.status == "published":  # type: ignore[attr-defined]
        await activity.record(
            ctx,
            "tagged",
            board_id=card.board_id,
            card=card,
            details={"tag_id": str(tag.id), "tag": tag.name},
        )
    return card


async def untag(ctx: Ctx, card: Card, tag_id: uuid.UUID) -> Card:
    result = await ctx.db.execute(
        delete(CardTag).where(CardTag.card_id == card.id, CardTag.tag_id == tag_id)
    )
    if result.rowcount and card.status == "published":  # type: ignore[attr-defined]
        tag = await ctx.db.get(Tag, tag_id)
        await activity.record(
            ctx,
            "untagged",
            board_id=card.board_id,
            card=card,
            details={"tag_id": str(tag_id), "tag": tag.name if tag else None},
        )
    return card


async def remove(ctx: Ctx, card: Card, board: Board) -> list[str]:
    """Delete a card. Returns the volume paths of its attachments for cleanup after commit."""
    if card.created_by != ctx.me.id and not can_admin_board(ctx, board):
        raise Forbidden("Only the card's author or a board admin can delete it")
    paths = list(
        await ctx.db.scalars(select(Attachment.volume_path).where(Attachment.card_id == card.id))
    )
    if card.status == "published":
        await activity.record(
            ctx,
            "deleted",
            board_id=card.board_id,
            card=card,
            touch=False,
            details={"number": card.number, "title": card.title},
        )
    else:
        await ctx.bump_board(card.board_id)
    await ctx.db.delete(card)
    return paths


def _require_published(card: Card) -> None:
    if card.status != "published":
        raise Conflict("Publish this draft first")
