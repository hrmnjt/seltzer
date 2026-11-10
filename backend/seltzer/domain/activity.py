"""The event log and the notifications it fans out.

Every change worth a stamp calls `record()` in the same transaction as the
change. Recording an event "touches" the card (resets its auto-postpone clock)
and bumps the board's version so pollers refetch.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from seltzer.db.models import (
    Assignment,
    Board,
    BoardAccess,
    BoardWatch,
    Card,
    Event,
    Notification,
    User,
    Watch,
)
from seltzer.domain.context import Ctx
from seltzer.ids import uuid7

ACTIONS = frozenset(
    {
        "published",
        "triaged",
        "moved",
        "sent_back_to_triage",
        "postponed",
        "auto_postponed",
        "resumed",
        "closed",
        "reopened",
        "gilded",
        "ungilded",
        "assigned",
        "unassigned",
        "tagged",
        "untagged",
        "title_changed",
        "description_changed",
        "board_changed",
        "commented",
        "step_added",
        "step_completed",
        "step_uncompleted",
        "attached",
        "deleted",
    }
)

# Actions that notify watchers and assignees. Mentions always notify.
NOTIFYING = frozenset(
    {
        "published",
        "triaged",
        "moved",
        "sent_back_to_triage",
        "postponed",
        "auto_postponed",
        "resumed",
        "closed",
        "reopened",
        "assigned",
        "commented",
        "board_changed",
    }
)

_SYSTEM = object()


async def record(
    ctx: Ctx,
    action: str,
    *,
    board_id: uuid.UUID,
    card: Card | None = None,
    details: dict[str, Any] | None = None,
    actor: Any = _SYSTEM,
    touch: bool = True,
    mentions: set[uuid.UUID] | None = None,
    assignee: uuid.UUID | None = None,
) -> Event:
    assert action in ACTIONS, action
    actor_id = (ctx.user.id if ctx.user else None) if actor is _SYSTEM else actor
    event = Event(
        id=uuid7(),
        board_id=board_id,
        card_id=card.id if card else None,
        actor_id=actor_id,
        action=action,
        details=details or {},
        created_at=ctx.now,
    )
    ctx.db.add(event)
    if card is not None and touch:
        card.last_active_at = ctx.now
        card.updated_at = ctx.now
    await ctx.bump_board(board_id)
    await ctx.db.flush()
    if card is not None and card.status == "published":
        await _notify(ctx, event, card, mentions or set(), assignee)
    return event


async def _notify(
    ctx: Ctx,
    event: Event,
    card: Card,
    mentions: set[uuid.UUID],
    assignee: uuid.UUID | None,
) -> None:
    reasons: dict[uuid.UUID, str] = {}
    if event.action in NOTIFYING:
        watchers = await ctx.db.scalars(select(Watch.user_id).where(Watch.card_id == card.id))
        board_watchers = await ctx.db.scalars(
            select(BoardWatch.user_id).where(BoardWatch.board_id == card.board_id)
        )
        for uid in [*watchers, *board_watchers]:
            reasons[uid] = "watching"
        assignees = await ctx.db.scalars(
            select(Assignment.user_id).where(Assignment.card_id == card.id)
        )
        for uid in assignees:
            reasons[uid] = "assigned"
    if assignee is not None:
        reasons[assignee] = "assigned"
    for uid in mentions:
        reasons[uid] = "mentioned"
    if event.actor_id is not None:
        reasons.pop(event.actor_id, None)  # actors never notify themselves
    if not reasons:
        return

    board = await ctx.db.get(Board, card.board_id)
    assert board is not None
    allowed = select(User.id).where(User.id.in_(reasons), User.active)
    if not board.all_access:
        on_list = select(BoardAccess.user_id).where(BoardAccess.board_id == board.id)
        allowed = allowed.where(
            or_(
                User.role.in_(("owner", "admin")),
                User.id == board.created_by,
                User.id.in_(on_list),
            )
        )
    recipients = list(await ctx.db.scalars(allowed))
    if not recipients:
        return
    await ctx.db.execute(
        pg_insert(Notification),
        [
            {
                "id": uuid7(),
                "user_id": uid,
                "card_id": card.id,
                "event_id": event.id,
                "reason": reasons[uid],
                "created_at": ctx.now,
            }
            for uid in recipients
        ],
    )


async def watch(ctx: Ctx, card: Card, user_id: uuid.UUID) -> None:
    await ctx.db.execute(
        pg_insert(Watch)
        .values(card_id=card.id, user_id=user_id, created_at=ctx.now)
        .on_conflict_do_nothing()
    )
