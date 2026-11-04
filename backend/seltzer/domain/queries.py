"""Read models: board snapshots, card tiles and detail, timeline, inbox and search."""

from __future__ import annotations

import base64
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Select, case, func, literal, or_, select, tuple_
from sqlalchemy.dialects.postgresql import aggregate_order_by, array_agg, distinct_on

from seltzer.api.schemas import (
    AttachmentOut,
    BoardCounts,
    BoardSnapshot,
    BoardSummary,
    CardDetail,
    CardPage,
    CardTile,
    ColumnOut,
    CommentOut,
    EventOut,
    EventPage,
    NotificationGroup,
    NotificationPage,
    ReactionOut,
    SearchHit,
    SearchResults,
    Stamp,
    StepOut,
    TagOut,
    UserBrief,
)
from seltzer.db.models import (
    Assignment,
    Attachment,
    Board,
    BoardWatch,
    Card,
    CardTag,
    Column,
    Comment,
    Event,
    Notification,
    Pin,
    Reaction,
    Step,
    Tag,
    User,
    Watch,
    WorkspaceSettings,
)
from seltzer.domain.context import Ctx
from seltzer.domain.errors import Invalid
from seltzer.domain.permissions import can_admin_board, visible_boards, visible_cards

CLOSING_SOON_AT = 0.75
STAMP_ACTIONS = (
    "published",
    "triaged",
    "moved",
    "sent_back_to_triage",
    "postponed",
    "auto_postponed",
    "resumed",
    "closed",
    "reopened",
)

View = Literal["open", "maybe", "not_now", "done", "golden", "closing_soon", "drafts"]
Sort = Literal["newest", "oldest", "activity", "changed"]


# Helpers --------------------------------------------------------------------------


async def workspace_default(ctx: Ctx) -> int:
    value = await ctx.db.scalar(select(WorkspaceSettings.default_auto_postpone_days))
    return value or 30


def period_of(board: Board, default: int) -> int:
    return board.auto_postpone_days or default


async def users_map(ctx: Ctx, ids: Iterable[uuid.UUID | None]) -> dict[str, UserBrief]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await ctx.db.scalars(select(User).where(User.id.in_(wanted)))
    return {str(u.id): UserBrief.model_validate(u) for u in rows}


def _encode(*parts: Any) -> str:
    raw = json.dumps([p.isoformat() if isinstance(p, datetime) else str(p) for p in parts])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode(cursor: str) -> list[str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()))
        assert isinstance(value, list)
        return value
    except Exception as exc:
        raise Invalid("Bad cursor") from exc


# Tiles -------------------------------------------------------------------------------


async def tiles(ctx: Ctx, cards: Sequence[Card]) -> list[CardTile]:
    if not cards:
        return []
    ids = [c.id for c in cards]
    db = ctx.db

    tags: dict[uuid.UUID, list[TagOut]] = defaultdict(list)
    for card_id, tag in await db.execute(
        select(CardTag.card_id, Tag)
        .join(Tag, Tag.id == CardTag.tag_id)
        .where(CardTag.card_id.in_(ids))
        .order_by(Tag.name)
    ):
        tags[card_id].append(TagOut.model_validate(tag))

    assignees: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for card_id, user_id in await db.execute(
        select(Assignment.card_id, Assignment.user_id)
        .where(Assignment.card_id.in_(ids))
        .order_by(Assignment.created_at)
    ):
        assignees[card_id].append(user_id)

    steps = {
        card_id: (total, done)
        for card_id, total, done in await db.execute(
            select(Step.card_id, func.count(), func.count(Step.completed_at))
            .where(Step.card_id.in_(ids))
            .group_by(Step.card_id)
        )
    }
    comments = dict(
        (
            await db.execute(
                select(Comment.card_id, func.count())
                .where(Comment.card_id.in_(ids))
                .group_by(Comment.card_id)
            )
        )
        .all()
    )
    attachments = dict(
        (
            await db.execute(
                select(Attachment.card_id, func.count())
                .where(Attachment.card_id.in_(ids))
                .group_by(Attachment.card_id)
            )
        )
        .all()
    )
    stamps = {
        row.card_id: Stamp(action=row.action, actor_id=row.actor_id, at=row.created_at)
        for row in await db.execute(
            select(Event.card_id, Event.action, Event.actor_id, Event.created_at)
            .where(Event.card_id.in_(ids), Event.action.in_(STAMP_ACTIONS))
            .ext(distinct_on(Event.card_id))
            .order_by(Event.card_id, Event.id.desc())
        )
    }
    default = await workspace_default(ctx)
    board_ids = {c.board_id for c in cards}
    periods = {
        b.id: period_of(b, default)
        for b in await db.scalars(select(Board).where(Board.id.in_(board_ids)))
    }

    out = []
    for c in cards:
        postpone_at = None
        closing_soon = False
        if c.status == "published" and c.state == "active":
            period = timedelta(days=periods[c.board_id])
            postpone_at = c.last_active_at + period
            closing_soon = ctx.now >= c.last_active_at + period * CLOSING_SOON_AT
        total, done = steps.get(c.id, (0, 0))
        out.append(
            CardTile(
                id=c.id,
                number=c.number,
                title=c.title,
                board_id=c.board_id,
                column_id=c.column_id,
                status=c.status,  # type: ignore[arg-type]
                state=c.state,  # type: ignore[arg-type]
                position=c.position,
                golden=c.golden_at is not None,
                auto_postponed=c.auto_postponed,
                tags=tags.get(c.id, []),
                assignee_ids=assignees.get(c.id, []),
                steps_total=total,
                steps_done=done,
                comments_count=comments.get(c.id, 0),
                attachments_count=attachments.get(c.id, 0),
                created_by=c.created_by,
                created_at=c.created_at,
                last_active_at=c.last_active_at,
                state_changed_at=c.state_changed_at,
                state_changed_by=c.state_changed_by,
                auto_postpone_at=postpone_at,
                closing_soon=closing_soon,
                stamp=stamps.get(c.id),
                version=c.version,
            )
        )
    return out


def tile_user_ids(items: Iterable[CardTile]) -> set[uuid.UUID | None]:
    ids: set[uuid.UUID | None] = set()
    for t in items:
        ids.add(t.created_by)
        ids.add(t.state_changed_by)
        ids.update(t.assignee_ids)
        if t.stamp:
            ids.add(t.stamp.actor_id)
    return ids


async def card_response(ctx: Ctx, card: Card) -> tuple[CardTile, dict[str, UserBrief]]:
    await ctx.db.flush()
    await ctx.db.refresh(card)
    [tile] = await tiles(ctx, [card])
    return tile, await users_map(ctx, tile_user_ids([tile]))


# Boards ---------------------------------------------------------------------------------


async def board_summaries(ctx: Ctx, boards: Sequence[Board]) -> list[BoardSummary]:
    if not boards:
        return []
    ids = [b.id for b in boards]
    counts: dict[uuid.UUID, BoardCounts] = defaultdict(BoardCounts)
    for board_id, state, in_maybe, n in await ctx.db.execute(
        select(Card.board_id, Card.state, Card.column_id.is_(None), func.count())
        .where(Card.board_id.in_(ids), Card.status == "published")
        .group_by(Card.board_id, Card.state, Card.column_id.is_(None))
    ):
        c = counts[board_id]
        if state == "active":
            c.open += n
            if in_maybe:
                c.maybe += n
        elif state == "not_now":
            c.not_now += n
        else:
            c.done += n
    watching = set(
        await ctx.db.scalars(
            select(BoardWatch.board_id).where(
                BoardWatch.board_id.in_(ids), BoardWatch.user_id == ctx.me.id
            )
        )
    )
    default = await workspace_default(ctx)
    return [
        BoardSummary(
            id=b.id,
            name=b.name,
            all_access=b.all_access,
            auto_postpone_days=b.auto_postpone_days,
            effective_auto_postpone_days=period_of(b, default),
            archived_at=b.archived_at,
            created_by=b.created_by,
            can_admin=can_admin_board(ctx, b),
            watching=b.id in watching,
            counts=counts[b.id],
            version=b.version,
        )
        for b in boards
    ]


async def list_boards(ctx: Ctx, *, include_archived: bool = False) -> list[BoardSummary]:
    stmt = select(Board).where(visible_boards(ctx)).order_by(func.lower(Board.name))
    if not include_archived:
        stmt = stmt.where(Board.archived_at.is_(None))
    return await board_summaries(ctx, list(await ctx.db.scalars(stmt)))


def _lane_order(stmt: Select[Any]) -> Select[Any]:
    # Golden cards sort to the top of their column (and of Maybe?).
    return stmt.order_by(Card.golden_at.is_(None), Card.position)


async def snapshot(ctx: Ctx, board: Board) -> BoardSnapshot:
    [summary] = await board_summaries(ctx, [board])
    columns = list(
        await ctx.db.scalars(
            select(Column).where(Column.board_id == board.id).order_by(Column.position)
        )
    )
    open_cards = list(
        await ctx.db.scalars(
            _lane_order(
                select(Card).where(
                    Card.board_id == board.id, Card.status == "published", Card.state == "active"
                )
            )
        )
    )
    drafts = list(
        await ctx.db.scalars(
            select(Card)
            .where(Card.board_id == board.id, Card.status == "draft", Card.created_by == ctx.me.id)
            .order_by(Card.created_at.desc())
        )
    )
    open_tiles = await tiles(ctx, open_cards)
    draft_tiles = await tiles(ctx, drafts)
    all_tags = [
        TagOut.model_validate(t) for t in await ctx.db.scalars(select(Tag).order_by(Tag.name))
    ]
    users = await users_map(ctx, tile_user_ids(open_tiles + draft_tiles) | {board.created_by})
    return BoardSnapshot(
        board=summary,
        columns=[ColumnOut.model_validate(c) for c in columns],
        cards=open_tiles,
        drafts=draft_tiles,
        users=users,
        tags=all_tags,
        version=board.version,
    )


async def list_cards(
    ctx: Ctx,
    board: Board,
    *,
    view: View = "open",
    tag_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    sort: Sort | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> CardPage:
    stmt = select(Card).where(Card.board_id == board.id, visible_cards(ctx))
    published = Card.status == "published"
    if view == "drafts":
        stmt = stmt.where(Card.status == "draft", Card.created_by == ctx.me.id)
    elif view == "open":
        stmt = stmt.where(published, Card.state == "active")
    elif view == "maybe":
        stmt = stmt.where(published, Card.state == "active", Card.column_id.is_(None))
    elif view == "not_now":
        stmt = stmt.where(published, Card.state == "not_now")
    elif view == "done":
        stmt = stmt.where(published, Card.state == "done")
    elif view == "golden":
        stmt = stmt.where(published, Card.golden_at.is_not(None), Card.state != "done")
    elif view == "closing_soon":
        period = period_of(board, await workspace_default(ctx))
        threshold = ctx.now - timedelta(days=period) * CLOSING_SOON_AT
        stmt = stmt.where(published, Card.state == "active", Card.last_active_at <= threshold)
    if tag_id is not None:
        stmt = stmt.where(Card.id.in_(select(CardTag.card_id).where(CardTag.tag_id == tag_id)))
    if assignee_id is not None:
        stmt = stmt.where(
            Card.id.in_(select(Assignment.card_id).where(Assignment.user_id == assignee_id))
        )

    sort = sort or ("changed" if view in ("not_now", "done") else "newest")
    key, descending = {
        "newest": (Card.created_at, True),
        "oldest": (Card.created_at, False),
        "activity": (Card.last_active_at, True),
        "changed": (func.coalesce(Card.state_changed_at, Card.created_at), True),
    }[sort]
    if cursor:
        at, cid = _decode(cursor)
        pair = tuple_(key, Card.id)
        bound = tuple_(literal(datetime.fromisoformat(at)), literal(uuid.UUID(cid)))
        stmt = stmt.where(pair < bound if descending else pair > bound)
    stmt = stmt.order_by(key.desc(), Card.id.desc()) if descending else stmt.order_by(key, Card.id)
    rows = list(await ctx.db.scalars(stmt.limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if more:
        last = rows[-1]
        value = {
            "newest": last.created_at,
            "oldest": last.created_at,
            "activity": last.last_active_at,
            "changed": last.state_changed_at or last.created_at,
        }[sort]
        next_cursor = _encode(value, last.id)
    items = await tiles(ctx, rows)
    return CardPage(
        cards=items, users=await users_map(ctx, tile_user_ids(items)), next_cursor=next_cursor
    )


async def tiles_for_ids(ctx: Ctx, ids: Sequence[uuid.UUID]) -> list[CardTile]:
    if not ids:
        return []
    cards = {
        c.id: c
        for c in await ctx.db.scalars(
            select(Card)
            .join(Board, Board.id == Card.board_id)
            .where(Card.id.in_(ids), visible_boards(ctx), visible_cards(ctx))
        )
    }
    return await tiles(ctx, [cards[i] for i in ids if i in cards])


# Card detail -------------------------------------------------------------------------------


async def card_detail(ctx: Ctx, card: Card, board: Board) -> CardDetail:
    await ctx.db.refresh(card)
    [tile] = await tiles(ctx, [card])
    column = await ctx.db.get(Column, card.column_id) if card.column_id else None
    steps = [
        StepOut.model_validate(s)
        for s in await ctx.db.scalars(
            select(Step).where(Step.card_id == card.id).order_by(Step.position)
        )
    ]
    comment_rows = list(
        await ctx.db.scalars(select(Comment).where(Comment.card_id == card.id).order_by(Comment.id))
    )
    reactions: dict[uuid.UUID, dict[str, list[uuid.UUID]]] = defaultdict(lambda: defaultdict(list))
    if comment_rows:
        for r in await ctx.db.scalars(
            select(Reaction)
            .where(Reaction.comment_id.in_([c.id for c in comment_rows]))
            .order_by(Reaction.created_at)
        ):
            reactions[r.comment_id][r.emoji].append(r.user_id)
    comments = [
        CommentOut(
            id=c.id,
            card_id=c.card_id,
            author_id=c.author_id,
            body=c.body,
            created_at=c.created_at,
            edited_at=c.edited_at,
            reactions=[
                ReactionOut(emoji=e, count=len(uids), user_ids=uids, mine=ctx.me.id in uids)
                for e, uids in reactions[c.id].items()
            ],
        )
        for c in comment_rows
    ]
    attachments = [
        AttachmentOut.model_validate(a)
        for a in await ctx.db.scalars(
            select(Attachment).where(Attachment.card_id == card.id).order_by(Attachment.id)
        )
    ]
    events = await _events(ctx, select(Event).where(Event.card_id == card.id), limit=100)
    watching = await ctx.db.scalar(
        select(func.count()).where(Watch.card_id == card.id, Watch.user_id == ctx.me.id)
    )
    pinned = await ctx.db.scalar(
        select(func.count()).where(Pin.card_id == card.id, Pin.user_id == ctx.me.id)
    )
    people: set[uuid.UUID | None] = tile_user_ids([tile])
    people.update(c.author_id for c in comments)
    people.update(uid for c in comments for r in c.reactions for uid in r.user_ids)
    people.update(a.uploaded_by for a in attachments)
    people.update(s.completed_by for s in steps)
    people.update(e.actor_id for e in events)
    return CardDetail(
        card=tile,
        description=card.description,
        board_name=board.name,
        column_name=column.name if column else None,
        steps=steps,
        comments=comments,
        attachments=attachments,
        events=events,
        watching=bool(watching),
        pinned=bool(pinned),
        can_delete=card.created_by == ctx.me.id or can_admin_board(ctx, board),
        users=await users_map(ctx, people),
    )


# Timeline -------------------------------------------------------------------------------------


async def _events(ctx: Ctx, stmt: Select[Any], *, limit: int) -> list[EventOut]:
    rows = list(await ctx.db.scalars(stmt.order_by(Event.id.desc()).limit(limit)))
    card_ids = {e.card_id for e in rows if e.card_id}
    cards = (
        {c.id: c for c in await ctx.db.scalars(select(Card).where(Card.id.in_(card_ids)))}
        if card_ids
        else {}
    )
    board_ids = {e.board_id for e in rows}
    boards = (
        {b.id: b.name for b in await ctx.db.scalars(select(Board).where(Board.id.in_(board_ids)))}
        if board_ids
        else {}
    )
    out = []
    for e in rows:
        card = cards.get(e.card_id) if e.card_id else None
        out.append(
            EventOut(
                id=e.id,
                board_id=e.board_id,
                board_name=boards.get(e.board_id),
                card_id=e.card_id,
                card_number=card.number if card else e.details.get("number"),
                card_title=card.title if card else e.details.get("title"),
                actor_id=e.actor_id,
                action=e.action,
                details=e.details,
                created_at=e.created_at,
            )
        )
    return out


async def timeline(
    ctx: Ctx,
    *,
    board_id: uuid.UUID | None = None,
    before: uuid.UUID | None = None,
    limit: int = 50,
) -> EventPage:
    visible = select(Board.id).where(visible_boards(ctx))
    stmt = select(Event).where(Event.board_id.in_(visible))
    if board_id is not None:
        stmt = stmt.where(Event.board_id == board_id)
    if before is not None:
        stmt = stmt.where(Event.id < before)
    events = await _events(ctx, stmt, limit=limit + 1)
    more = len(events) > limit
    events = events[:limit]
    return EventPage(
        events=events,
        users=await users_map(ctx, (e.actor_id for e in events)),
        next_cursor=str(events[-1].id) if more else None,
    )


# Notifications -----------------------------------------------------------------------------------


async def unread_count(ctx: Ctx) -> int:
    """Unread cards, not unread rows: the tray stacks per card."""
    value = await ctx.db.scalar(
        select(func.count(func.distinct(Notification.card_id))).where(
            Notification.user_id == ctx.me.id, Notification.read_at.is_(None)
        )
    )
    return value or 0


async def notifications(
    ctx: Ctx, *, before: uuid.UUID | None = None, limit: int = 30
) -> NotificationPage:
    # Postgres has no max(uuid); UUIDv7 ids sort by time, so take the first id in descending order.
    latest = array_agg(aggregate_order_by(Notification.event_id, Notification.event_id.desc()))[1]
    stmt = (
        select(
            Notification.card_id,
            latest.label("latest_event"),
            func.count().label("total"),
            func.count().filter(Notification.read_at.is_(None)).label("unread"),
            func.array_agg(func.distinct(Notification.reason)).label("reasons"),
        )
        .where(Notification.user_id == ctx.me.id)
        .group_by(Notification.card_id)
        .order_by(latest.desc())
        .limit(limit + 1)
    )
    if before is not None:
        stmt = stmt.having(latest < before)
    groups = list(await ctx.db.execute(stmt))
    more = len(groups) > limit
    groups = groups[:limit]
    if not groups:
        return NotificationPage(groups=[], users={}, next_cursor=None)

    card_ids = [g.card_id for g in groups]
    events = {
        e.id: e
        for e in await _events(
            ctx, select(Event).where(Event.id.in_([g.latest_event for g in groups])), limit=limit
        )
    }
    actors: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for card_id, actor_id in await ctx.db.execute(
        select(Event.card_id, Event.actor_id)
        .join(Notification, Notification.event_id == Event.id)
        .where(Notification.user_id == ctx.me.id, Notification.card_id.in_(card_ids))
        .group_by(Event.card_id, Event.actor_id)
        .order_by(Event.card_id, func.max(Event.created_at).desc())
    ):
        if actor_id is not None and card_id is not None:
            actors[card_id].append(actor_id)
    cards = {
        c.id: (c, b)
        for c, b in await ctx.db.execute(
            select(Card, Board).join(Board, Board.id == Card.board_id).where(Card.id.in_(card_ids))
        )
    }
    out = []
    for g in groups:
        if g.card_id not in cards or g.latest_event not in events:
            continue
        card, board = cards[g.card_id]
        out.append(
            NotificationGroup(
                card_id=card.id,
                card_number=card.number,
                card_title=card.title,
                board_id=board.id,
                board_name=board.name,
                unread=g.unread,
                total=g.total,
                latest=events[g.latest_event],
                actor_ids=actors[card.id][:5],
                reasons=sorted(g.reasons),
            )
        )
    people = {a for ids in actors.values() for a in ids}
    return NotificationPage(
        groups=out,
        users=await users_map(ctx, people),
        next_cursor=str(groups[-1].latest_event) if more else None,
    )


# Search ------------------------------------------------------------------------------------------


async def search(
    ctx: Ctx, q: str, *, board_id: uuid.UUID | None = None, limit: int = 30
) -> SearchResults:
    q = " ".join(q.split())[:200]
    if not q:
        return SearchResults(hits=[], users={})
    query = func.websearch_to_tsquery("english", q)
    in_comments = select(Comment.card_id).where(Comment.search.op("@@")(query)).scalar_subquery()
    title_like = Card.title.ilike(f"%{_escape_like(q)}%", escape="\\")
    # "q <% title": q is close to some word of the title (typo-tolerant, uses the trigram index).
    fuzzy = literal(q).op("<%")(Card.title)
    rank = (
        func.ts_rank(Card.search, query)
        + func.word_similarity(q, Card.title)
        + case((title_like, 0.5), else_=0.0)
    )
    stmt = (
        select(Card, Board.name, rank.label("rank"))
        .join(Board, Board.id == Card.board_id)
        .where(
            visible_boards(ctx),
            visible_cards(ctx),
            Board.archived_at.is_(None),
            or_(Card.search.op("@@")(query), title_like, fuzzy, Card.id.in_(in_comments)),
        )
        .order_by(rank.desc(), Card.number.desc())
        .limit(limit)
    )
    if board_id is not None:
        stmt = stmt.where(Card.board_id == board_id)
    rows = list(await ctx.db.execute(stmt))
    if not rows:
        return SearchResults(hits=[], users={})
    cards = [r[0] for r in rows]
    snippets = await _snippets(ctx, [c.id for c in cards], query)
    items = await tiles(ctx, cards)
    hits = [
        SearchHit(card=t, board_name=r[1], snippet=snippets.get(t.id))
        for t, r in zip(items, rows, strict=True)
    ]
    return SearchResults(hits=hits, users=await users_map(ctx, tile_user_ids(items)))


async def _snippets(ctx: Ctx, card_ids: list[uuid.UUID], query: Any) -> dict[uuid.UUID, str]:
    opts = "StartSel=«, StopSel=», MaxWords=18, MinWords=6, MaxFragments=1"
    out: dict[uuid.UUID, str] = {}
    for card_id, text in await ctx.db.execute(
        select(Card.id, func.ts_headline("english", Card.description_text, query, opts)).where(
            Card.id.in_(card_ids), Card.search.op("@@")(query), Card.description_text != ""
        )
    ):
        out[card_id] = text
    for card_id, text in await ctx.db.execute(
        select(Comment.card_id, func.ts_headline("english", Comment.body_text, query, opts))
        .where(Comment.card_id.in_(card_ids), Comment.search.op("@@")(query))
        .ext(distinct_on(Comment.card_id))
        .order_by(Comment.card_id, Comment.id.desc())
    ):
        out.setdefault(card_id, text)
    return out


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
