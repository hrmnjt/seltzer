"""Steps, comments, reactions, attachments and pins: the things that hang off a card."""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, BinaryIO

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from seltzer import richtext
from seltzer.db.models import Attachment, Board, Card, Comment, Pin, Reaction, Step
from seltzer.domain import activity
from seltzer.domain.context import Ctx
from seltzer.domain.errors import Forbidden, Invalid, NotFound, TooLarge
from seltzer.domain.permissions import can_admin_board, get_card
from seltzer.domain.positions import place
from seltzer.files import FileStore
from seltzer.ids import uuid7

MAX_STEP = 500
MAX_REACTION = 16


def _record_if_published(card: Card) -> bool:
    return card.status == "published"


# Steps -----------------------------------------------------------------------


async def add_step(
    ctx: Ctx,
    card: Card,
    body: str,
    *,
    above: uuid.UUID | None = None,
    below: uuid.UUID | None = None,
) -> Step:
    body = body.strip()
    if not body or len(body) > MAX_STEP:
        raise Invalid(f"Steps need 1 to {MAX_STEP} characters")
    step = Step(card_id=card.id, body=body, position="V", created_at=ctx.now)
    step.position = await place(
        ctx,
        Step,
        Step.card_id == card.id,
        key_col=Step.id,
        item_key=None,
        above=above,
        below=below,
        default="bottom",
    )
    ctx.db.add(step)
    if _record_if_published(card):
        await activity.record(
            ctx, "step_added", board_id=card.board_id, card=card, details={"step": body}
        )
    else:
        await ctx.db.flush()
    return step


async def get_step(ctx: Ctx, step_id: uuid.UUID) -> tuple[Step, Card]:
    step = await ctx.db.get(Step, step_id)
    if step is None:
        raise NotFound("No such step")
    card = await ctx.db.get(Card, step.card_id)
    assert card is not None
    await get_card(ctx, card.number, write=True)  # permission check
    return step, card


async def update_step(ctx: Ctx, step: Step, card: Card, changes: dict[str, Any]) -> Step:
    if changes.get("body") is not None:
        body = changes["body"].strip()
        if not body or len(body) > MAX_STEP:
            raise Invalid(f"Steps need 1 to {MAX_STEP} characters")
        step.body = body
        await ctx.bump_board(card.board_id)
    if changes.get("completed") is not None:
        done = bool(changes["completed"])
        if done != (step.completed_at is not None):
            step.completed_at = ctx.now if done else None
            step.completed_by = ctx.me.id if done else None
            if _record_if_published(card):
                await activity.record(
                    ctx,
                    "step_completed" if done else "step_uncompleted",
                    board_id=card.board_id,
                    card=card,
                    details={"step": step.body},
                )
    if changes.get("above") is not None or changes.get("below") is not None:
        step.position = await place(
            ctx,
            Step,
            Step.card_id == card.id,
            key_col=Step.id,
            item_key=step.id,
            above=changes.get("above"),
            below=changes.get("below"),
        )
    return step


async def delete_step(ctx: Ctx, step: Step, card: Card) -> None:
    await ctx.db.delete(step)
    await ctx.bump_board(card.board_id)


# Comments and reactions --------------------------------------------------------


def _check_body(body: dict[str, Any]) -> str:
    try:
        richtext.validate(body)
    except richtext.RichTextError as exc:
        raise Invalid(str(exc)) from exc
    text = richtext.plain_text(body)
    if not text.strip():
        raise Invalid("A comment can't be empty")
    return text


async def add_comment(ctx: Ctx, card: Card, body: dict[str, Any]) -> Comment:
    text = _check_body(body)
    comment = Comment(
        id=uuid7(),
        card_id=card.id,
        author_id=ctx.me.id,
        body=body,
        body_text=text,
        created_at=ctx.now,
    )
    ctx.db.add(comment)
    await activity.watch(ctx, card, ctx.me.id)  # commenting follows the card
    if _record_if_published(card):
        await activity.record(
            ctx,
            "commented",
            board_id=card.board_id,
            card=card,
            details={"comment_id": str(comment.id), "excerpt": text[:140]},
            mentions=richtext.mentioned_user_ids(body),
        )
    else:
        await ctx.db.flush()
    return comment


async def get_comment(ctx: Ctx, comment_id: uuid.UUID) -> tuple[Comment, Card, Board]:
    comment = await ctx.db.get(Comment, comment_id)
    if comment is None:
        raise NotFound("No such comment")
    card = await ctx.db.get(Card, comment.card_id)
    assert card is not None
    card, board = await get_card(ctx, card.number)
    return comment, card, board


async def edit_comment(ctx: Ctx, comment: Comment, card: Card, body: dict[str, Any]) -> Comment:
    if comment.author_id != ctx.me.id:
        raise Forbidden("Only the author can edit a comment")
    comment.body_text = _check_body(body)
    comment.body = body
    comment.edited_at = ctx.now
    await ctx.bump_board(card.board_id)
    return comment


async def delete_comment(ctx: Ctx, comment: Comment, card: Card, board: Board) -> None:
    if comment.author_id != ctx.me.id and not can_admin_board(ctx, board):
        raise Forbidden("Only the author or a board admin can delete a comment")
    await ctx.db.delete(comment)
    await ctx.bump_board(card.board_id)


def _reaction(text: str) -> str:
    text = text.strip()
    if not text or len(text) > MAX_REACTION or any(c.isspace() for c in text):
        raise Invalid(f"Reactions are 1 to {MAX_REACTION} characters with no spaces")
    return text


async def react(ctx: Ctx, comment: Comment, emoji: str, on: bool) -> None:
    emoji = _reaction(emoji)
    if on:
        await ctx.db.execute(
            pg_insert(Reaction)
            .values(comment_id=comment.id, user_id=ctx.me.id, emoji=emoji, created_at=ctx.now)
            .on_conflict_do_nothing()
        )
    else:
        await ctx.db.execute(
            delete(Reaction).where(
                Reaction.comment_id == comment.id,
                Reaction.user_id == ctx.me.id,
                Reaction.emoji == emoji,
            )
        )


# Attachments -------------------------------------------------------------------

_UNSAFE = re.compile(r"[^\w.\- ()\[\]]+", re.UNICODE)


def safe_filename(name: str | None) -> str:
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = _UNSAFE.sub("_", base).strip(" .") or "file"
    stem, ext = os.path.splitext(base)
    return stem[: 120 - len(ext[:20])] + ext[:20]


async def add_attachment(
    ctx: Ctx,
    card: Card,
    store: FileStore,
    *,
    fileobj: BinaryIO,
    filename: str | None,
    content_type: str | None,
    size: int,
    comment_id: uuid.UUID | None = None,
) -> Attachment:
    limit = ctx.settings.seltzer_max_upload_mb * 1024 * 1024
    if size > limit:
        raise TooLarge(f"Attachments are limited to {ctx.settings.seltzer_max_upload_mb} MB")
    if comment_id is not None:
        comment = await ctx.db.get(Comment, comment_id)
        if comment is None or comment.card_id != card.id:
            raise NotFound("No such comment on this card")
    attachment_id = uuid7()
    name = safe_filename(filename)
    path = f"boards/{card.board_id}/cards/{card.id}/{attachment_id}/{name}"
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(store.upload, path, fileobj)
    attachment = Attachment(
        id=attachment_id,
        card_id=card.id,
        comment_id=comment_id,
        volume_path=path,
        filename=name,
        content_type=content_type or "application/octet-stream",
        bytes=size,
        uploaded_by=ctx.me.id,
        created_at=ctx.now,
    )
    ctx.db.add(attachment)
    if _record_if_published(card):
        await activity.record(
            ctx,
            "attached",
            board_id=card.board_id,
            card=card,
            details={"attachment_id": str(attachment_id), "filename": name},
        )
    else:
        await ctx.db.flush()
    return attachment


async def get_attachment(ctx: Ctx, attachment_id: uuid.UUID) -> tuple[Attachment, Card, Board]:
    attachment = await ctx.db.get(Attachment, attachment_id)
    if attachment is None:
        raise NotFound("No such attachment")
    card = await ctx.db.get(Card, attachment.card_id)
    assert card is not None
    # Volume grants belong to the app, so this board check is the only gate.
    card, board = await get_card(ctx, card.number)
    return attachment, card, board


async def delete_attachment(ctx: Ctx, attachment: Attachment, card: Card, board: Board) -> str:
    if attachment.uploaded_by != ctx.me.id and not can_admin_board(ctx, board):
        raise Forbidden("Only the uploader or a board admin can remove an attachment")
    await ctx.db.delete(attachment)
    await ctx.bump_board(card.board_id)
    return attachment.volume_path


# Pins --------------------------------------------------------------------------


async def set_pin(
    ctx: Ctx,
    card: Card,
    pinned: bool,
    *,
    above: uuid.UUID | None = None,
    below: uuid.UUID | None = None,
) -> None:
    if not pinned:
        await ctx.db.execute(delete(Pin).where(Pin.user_id == ctx.me.id, Pin.card_id == card.id))
        return
    position = await place(
        ctx,
        Pin,
        Pin.user_id == ctx.me.id,
        key_col=Pin.card_id,
        item_key=card.id,
        above=above,
        below=below,
    )
    await ctx.db.execute(
        pg_insert(Pin)
        .values(user_id=ctx.me.id, card_id=card.id, position=position, created_at=ctx.now)
        .on_conflict_do_update(index_elements=["user_id", "card_id"], set_={"position": position})
    )


async def pinned_card_ids(ctx: Ctx) -> list[uuid.UUID]:
    return list(
        await ctx.db.scalars(
            select(Pin.card_id).where(Pin.user_id == ctx.me.id).order_by(Pin.position)
        )
    )
