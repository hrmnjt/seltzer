"""/api/cards and the things on a card. Each lifecycle change has its own
endpoint, so rules and events live in one place."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete
from starlette.concurrency import run_in_threadpool

from seltzer.api.deps import get_ctx, get_store
from seltzer.api.schemas import (
    AttachmentOut,
    CardDetail,
    CardPatch,
    CardResponse,
    CardTile,
    CommentIn,
    CommentOut,
    PlaceIn,
    StepIn,
    StepOut,
    StepPatch,
    TriageIn,
)
from seltzer.db.models import Card, Comment, Watch
from seltzer.domain import activity, children, queries
from seltzer.domain import cards as lifecycle
from seltzer.domain.context import Ctx
from seltzer.domain.errors import Invalid
from seltzer.domain.permissions import get_card
from seltzer.files import FileStore

log = logging.getLogger(__name__)
router = APIRouter(tags=["cards"])

INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}


async def _respond(ctx: Ctx, card: Card) -> CardResponse:
    tile, users = await queries.card_response(ctx, card)
    await ctx.db.commit()
    return CardResponse(card=tile, users=users)


async def _act(ctx: Ctx, number: int, action: Callable[[Card], Awaitable[Card]]) -> CardResponse:
    card, _ = await get_card(ctx, number, write=True, lock=True)
    await action(card)
    return await _respond(ctx, card)


def _delete_files(store: FileStore, paths: list[str]) -> None:
    for path in paths:
        try:
            store.delete(path)
        except Exception:  # an orphaned file is harmless; log and move on
            log.warning("could not delete %s", path, exc_info=True)


# The card ------------------------------------------------------------------------------


@router.get("/cards/{number}")
async def card_detail(number: int, ctx: Ctx = Depends(get_ctx)) -> CardDetail:
    card, board = await get_card(ctx, number)
    return await queries.card_detail(ctx, card, board)


@router.patch("/cards/{number}")
async def edit_card(number: int, body: CardPatch, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    card, _ = await get_card(ctx, number, write=True, lock=True)
    fields = body.model_fields_set
    if "title" in fields and body.title is None:
        raise Invalid("A card needs a title")
    await lifecycle.edit(
        ctx,
        card,
        fields=fields,
        title=body.title,
        description=body.description,
        board_id=body.board_id,
        version=body.version,
    )
    return await _respond(ctx, card)


@router.delete("/cards/{number}", status_code=204)
async def delete_card(
    number: int,
    background: BackgroundTasks,
    ctx: Ctx = Depends(get_ctx),
    store: FileStore = Depends(get_store),
) -> Response:
    card, board = await get_card(ctx, number, write=True, lock=True)
    paths = await lifecycle.remove(ctx, card, board)
    await ctx.db.commit()
    background.add_task(_delete_files, store, paths)
    return Response(status_code=204)


# Lifecycle ----------------------------------------------------------------------------


@router.post("/cards/{number}/publish")
async def publish(number: int, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.publish(ctx, c))


@router.post("/cards/{number}/triage")
async def triage(number: int, body: TriageIn, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(
        ctx,
        number,
        lambda c: lifecycle.triage(ctx, c, body.column_id, above=body.above, below=body.below),
    )


@router.post("/cards/{number}/untriage")
async def untriage(
    number: int, body: PlaceIn | None = None, ctx: Ctx = Depends(get_ctx)
) -> CardResponse:
    place = body or PlaceIn()
    return await _act(
        ctx, number, lambda c: lifecycle.untriage(ctx, c, above=place.above, below=place.below)
    )


@router.post("/cards/{number}/reorder")
async def reorder_in_maybe(number: int, body: PlaceIn, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    """Reorder a card within Maybe?. Use /triage to reorder within a column."""
    return await _act(
        ctx,
        number,
        lambda c: lifecycle.reorder_in_maybe(ctx, c, above=body.above, below=body.below),
    )


@router.post("/cards/{number}/postpone")
async def postpone(number: int, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.postpone(ctx, c))


@router.post("/cards/{number}/resume")
async def resume(number: int, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.resume(ctx, c))


@router.post("/cards/{number}/close")
async def close(number: int, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.close(ctx, c))


@router.post("/cards/{number}/reopen")
async def reopen(number: int, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.reopen(ctx, c))


@router.put("/cards/{number}/golden")
async def gild(number: int, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.set_golden(ctx, c, True))


@router.delete("/cards/{number}/golden")
async def ungild(number: int, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.set_golden(ctx, c, False))


# Tags and assignees ---------------------------------------------------------------------


@router.put("/cards/{number}/tags/{tag_id}")
async def add_tag(number: int, tag_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.tag(ctx, c, tag_id))


@router.delete("/cards/{number}/tags/{tag_id}")
async def remove_tag(number: int, tag_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.untag(ctx, c, tag_id))


@router.put("/cards/{number}/assignees/{user_id}")
async def assign(number: int, user_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.assign(ctx, c, user_id))


@router.delete("/cards/{number}/assignees/{user_id}")
async def unassign(number: int, user_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> CardResponse:
    return await _act(ctx, number, lambda c: lifecycle.unassign(ctx, c, user_id))


# Watching and pins ----------------------------------------------------------------------------


@router.put("/cards/{number}/watch", status_code=204)
async def watch(number: int, ctx: Ctx = Depends(get_ctx)) -> Response:
    card, _ = await get_card(ctx, number)
    await activity.watch(ctx, card, ctx.me.id)
    await ctx.db.commit()
    return Response(status_code=204)


@router.delete("/cards/{number}/watch", status_code=204)
async def unwatch(number: int, ctx: Ctx = Depends(get_ctx)) -> Response:
    card, _ = await get_card(ctx, number)
    await ctx.db.execute(delete(Watch).where(Watch.card_id == card.id, Watch.user_id == ctx.me.id))
    await ctx.db.commit()
    return Response(status_code=204)


@router.put("/cards/{number}/pin", status_code=204)
async def pin(number: int, body: PlaceIn | None = None, ctx: Ctx = Depends(get_ctx)) -> Response:
    card, _ = await get_card(ctx, number)
    place = body or PlaceIn()
    await children.set_pin(ctx, card, True, above=place.above, below=place.below)
    await ctx.db.commit()
    return Response(status_code=204)


@router.delete("/cards/{number}/pin", status_code=204)
async def unpin(number: int, ctx: Ctx = Depends(get_ctx)) -> Response:
    card, _ = await get_card(ctx, number)
    await children.set_pin(ctx, card, False)
    await ctx.db.commit()
    return Response(status_code=204)


@router.get("/pins")
async def pins(ctx: Ctx = Depends(get_ctx)) -> list[CardTile]:
    return await queries.tiles_for_ids(ctx, await children.pinned_card_ids(ctx))


# Steps --------------------------------------------------------------------------------------


@router.post("/cards/{number}/steps", status_code=201)
async def add_step(number: int, body: StepIn, ctx: Ctx = Depends(get_ctx)) -> StepOut:
    card, _ = await get_card(ctx, number, write=True)
    step = await children.add_step(ctx, card, body.body, above=body.above, below=body.below)
    await ctx.db.flush()
    out = StepOut.model_validate(step)
    await ctx.db.commit()
    return out


@router.patch("/steps/{step_id}")
async def update_step(step_id: uuid.UUID, body: StepPatch, ctx: Ctx = Depends(get_ctx)) -> StepOut:
    step, card = await children.get_step(ctx, step_id)
    await children.update_step(ctx, step, card, body.model_dump(exclude_unset=True))
    await ctx.db.flush()
    out = StepOut.model_validate(step)
    await ctx.db.commit()
    return out


@router.delete("/steps/{step_id}", status_code=204)
async def delete_step(step_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    step, card = await children.get_step(ctx, step_id)
    await children.delete_step(ctx, step, card)
    await ctx.db.commit()
    return Response(status_code=204)


# Comments and reactions ------------------------------------------------------------------------


def _comment_out(comment: Comment) -> CommentOut:
    return CommentOut(
        id=comment.id,
        card_id=comment.card_id,
        author_id=comment.author_id,
        body=comment.body,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
        reactions=[],
    )


@router.post("/cards/{number}/comments", status_code=201)
async def add_comment(number: int, body: CommentIn, ctx: Ctx = Depends(get_ctx)) -> CommentOut:
    card, _ = await get_card(ctx, number, write=True)
    comment = await children.add_comment(ctx, card, body.body)
    out = _comment_out(comment)
    await ctx.db.commit()
    return out


@router.patch("/comments/{comment_id}")
async def edit_comment(
    comment_id: uuid.UUID, body: CommentIn, ctx: Ctx = Depends(get_ctx)
) -> CommentOut:
    comment, card, _ = await children.get_comment(ctx, comment_id)
    await children.edit_comment(ctx, comment, card, body.body)
    out = _comment_out(comment)
    await ctx.db.commit()
    return out


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    comment, card, board = await children.get_comment(ctx, comment_id)
    await children.delete_comment(ctx, comment, card, board)
    await ctx.db.commit()
    return Response(status_code=204)


@router.put("/comments/{comment_id}/reactions/{emoji}", status_code=204)
async def react(comment_id: uuid.UUID, emoji: str, ctx: Ctx = Depends(get_ctx)) -> Response:
    comment, card, _ = await children.get_comment(ctx, comment_id)
    await children.react(ctx, comment, emoji, True)
    await ctx.bump_board(card.board_id)
    await ctx.db.commit()
    return Response(status_code=204)


@router.delete("/comments/{comment_id}/reactions/{emoji}", status_code=204)
async def unreact(comment_id: uuid.UUID, emoji: str, ctx: Ctx = Depends(get_ctx)) -> Response:
    comment, card, _ = await children.get_comment(ctx, comment_id)
    await children.react(ctx, comment, emoji, False)
    await ctx.bump_board(card.board_id)
    await ctx.db.commit()
    return Response(status_code=204)


# Attachments --------------------------------------------------------------------------------------


@router.post("/cards/{number}/attachments", status_code=201)
async def upload(
    number: int,
    file: UploadFile = File(...),
    comment_id: uuid.UUID | None = Form(default=None),
    ctx: Ctx = Depends(get_ctx),
    store: FileStore = Depends(get_store),
) -> AttachmentOut:
    card, _ = await get_card(ctx, number, write=True)
    size = file.size
    if size is None:
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
    attachment = await children.add_attachment(
        ctx,
        card,
        store,
        fileobj=file.file,
        filename=file.filename,
        content_type=file.content_type,
        size=size,
        comment_id=comment_id,
    )
    out = AttachmentOut.model_validate(attachment)
    await ctx.db.commit()
    return out


@router.get(
    "/attachments/{attachment_id}",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download(
    attachment_id: uuid.UUID,
    ctx: Ctx = Depends(get_ctx),
    store: FileStore = Depends(get_store),
) -> StreamingResponse:
    attachment, _, _ = await children.get_attachment(ctx, attachment_id)
    await ctx.db.close()  # don't hold a connection while bytes stream
    inline = attachment.content_type in INLINE_TYPES
    disposition = "inline" if inline else "attachment"
    quoted = attachment.filename.replace('"', "")
    chunks = await run_in_threadpool(store.stream, attachment.volume_path)
    return StreamingResponse(
        chunks,
        media_type=attachment.content_type if inline else "application/octet-stream",
        headers={
            "Content-Disposition": f'{disposition}; filename="{quoted}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: uuid.UUID,
    background: BackgroundTasks,
    ctx: Ctx = Depends(get_ctx),
    store: FileStore = Depends(get_store),
) -> Response:
    attachment, card, board = await children.get_attachment(ctx, attachment_id)
    path = await children.delete_attachment(ctx, attachment, card, board)
    await ctx.db.commit()
    background.add_task(_delete_files, store, [path])
    return Response(status_code=204)
