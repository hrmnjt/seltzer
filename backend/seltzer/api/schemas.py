"""Pydantic request and response models. The OpenAPI schema built from these
generates the frontend's TypeScript types."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["owner", "admin", "member"]
CardState = Literal["active", "not_now", "done"]
CardStatus = Literal["draft", "published"]
RichText = dict[str, Any]


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# People ----------------------------------------------------------------------


class UserBrief(Model):
    id: uuid.UUID
    display_name: str
    email: str


class UserOut(UserBrief):
    role: Role
    active: bool
    last_seen_at: datetime | None


class MeOut(Model):
    user: UserOut
    unread_notifications: int
    workspace_default_auto_postpone_days: int


class UserPatch(BaseModel):
    role: Role | None = None
    active: bool | None = None


class SettingsOut(Model):
    default_auto_postpone_days: int


class SettingsPatch(BaseModel):
    default_auto_postpone_days: int = Field(ge=3, le=365)


# Tags --------------------------------------------------------------------------


class TagOut(Model):
    id: uuid.UUID
    name: str
    color: str


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = "gray"


class TagPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    color: str | None = None


# Boards and columns --------------------------------------------------------------


class ColumnOut(Model):
    id: uuid.UUID
    name: str
    color: str
    position: str


class ColumnIn(BaseModel):
    name: str
    color: str = "gray"
    above: uuid.UUID | None = Field(default=None, description="Column to the left of the new one")
    below: uuid.UUID | None = Field(default=None, description="Column to the right of the new one")


class ColumnPatch(BaseModel):
    name: str | None = None
    color: str | None = None
    above: uuid.UUID | None = None
    below: uuid.UUID | None = None


class BoardIn(BaseModel):
    name: str
    all_access: bool = True
    auto_postpone_days: int | None = Field(default=None, ge=3, le=365)
    columns: list[ColumnIn] = []


class BoardPatch(BaseModel):
    name: str | None = None
    all_access: bool | None = None
    auto_postpone_days: int | None = Field(
        default=None, ge=3, le=365, description="null resets to the workspace default"
    )
    archived: bool | None = None


class BoardCounts(BaseModel):
    maybe: int = 0
    open: int = 0
    not_now: int = 0
    done: int = 0


class BoardSummary(Model):
    id: uuid.UUID
    name: str
    all_access: bool
    auto_postpone_days: int | None
    effective_auto_postpone_days: int
    archived_at: datetime | None
    created_by: uuid.UUID
    can_admin: bool
    watching: bool
    counts: BoardCounts
    version: int


class AccessIn(BaseModel):
    user_ids: list[uuid.UUID]


class AccessOut(BaseModel):
    user_ids: list[uuid.UUID]


# Cards ---------------------------------------------------------------------------


class Stamp(BaseModel):
    action: str
    actor_id: uuid.UUID | None
    at: datetime


class CardTile(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    board_id: uuid.UUID
    column_id: uuid.UUID | None
    status: CardStatus
    state: CardState
    position: str
    golden: bool
    auto_postponed: bool
    tags: list[TagOut]
    assignee_ids: list[uuid.UUID]
    steps_total: int
    steps_done: int
    comments_count: int
    attachments_count: int
    created_by: uuid.UUID
    created_at: datetime
    last_active_at: datetime
    state_changed_at: datetime | None
    state_changed_by: uuid.UUID | None
    auto_postpone_at: datetime | None
    closing_soon: bool
    stamp: Stamp | None
    version: int


class CardIn(BaseModel):
    title: str
    description: RichText | None = None
    draft: bool = False


class CardPatch(BaseModel):
    title: str | None = None
    description: RichText | None = None
    board_id: uuid.UUID | None = None
    version: int | None = Field(default=None, description="The version you read; 409 if stale")


class TriageIn(BaseModel):
    column_id: uuid.UUID
    above: uuid.UUID | None = Field(default=None, description="Card shown above the drop point")
    below: uuid.UUID | None = Field(default=None, description="Card shown below the drop point")


class PlaceIn(BaseModel):
    above: uuid.UUID | None = None
    below: uuid.UUID | None = None


class StepOut(Model):
    id: uuid.UUID
    body: str
    position: str
    completed_at: datetime | None
    completed_by: uuid.UUID | None


class StepIn(BaseModel):
    body: str
    above: uuid.UUID | None = None
    below: uuid.UUID | None = None


class StepPatch(BaseModel):
    body: str | None = None
    completed: bool | None = None
    above: uuid.UUID | None = None
    below: uuid.UUID | None = None


class ReactionOut(BaseModel):
    emoji: str
    count: int
    user_ids: list[uuid.UUID]
    mine: bool


class CommentOut(BaseModel):
    id: uuid.UUID
    card_id: uuid.UUID
    author_id: uuid.UUID
    body: RichText
    created_at: datetime
    edited_at: datetime | None
    reactions: list[ReactionOut]


class CommentIn(BaseModel):
    body: RichText


class AttachmentOut(Model):
    id: uuid.UUID
    comment_id: uuid.UUID | None
    filename: str
    content_type: str
    bytes: int
    uploaded_by: uuid.UUID
    created_at: datetime


class EventOut(BaseModel):
    id: uuid.UUID
    board_id: uuid.UUID
    board_name: str | None = None
    card_id: uuid.UUID | None
    card_number: int | None
    card_title: str | None
    actor_id: uuid.UUID | None
    action: str
    details: dict[str, Any]
    created_at: datetime


class CardDetail(BaseModel):
    card: CardTile
    description: RichText | None
    board_name: str
    column_name: str | None
    steps: list[StepOut]
    comments: list[CommentOut]
    attachments: list[AttachmentOut]
    events: list[EventOut]
    watching: bool
    pinned: bool
    can_delete: bool
    users: dict[str, UserBrief]


class CardResponse(BaseModel):
    """A card tile plus the people it references, returned by every card write."""

    card: CardTile
    users: dict[str, UserBrief]


class CardPage(BaseModel):
    cards: list[CardTile]
    users: dict[str, UserBrief]
    next_cursor: str | None


class BoardSnapshot(BaseModel):
    board: BoardSummary
    columns: list[ColumnOut]
    cards: list[CardTile] = Field(description="Open cards: Maybe? and every column")
    drafts: list[CardTile] = Field(description="Your own drafts on this board")
    users: dict[str, UserBrief]
    tags: list[TagOut]
    version: int


# Activity, notifications, search ----------------------------------------------------


class EventPage(BaseModel):
    events: list[EventOut]
    users: dict[str, UserBrief]
    next_cursor: str | None


class NotificationGroup(BaseModel):
    card_id: uuid.UUID
    card_number: int
    card_title: str
    board_id: uuid.UUID
    board_name: str
    unread: int
    total: int
    latest: EventOut
    actor_ids: list[uuid.UUID]
    reasons: list[str]


class NotificationPage(BaseModel):
    groups: list[NotificationGroup]
    users: dict[str, UserBrief]
    next_cursor: str | None


class ReadIn(BaseModel):
    card_ids: list[uuid.UUID] | None = Field(default=None, description="Omit to mark everything")


class SearchHit(BaseModel):
    card: CardTile
    board_name: str
    snippet: str | None


class SearchResults(BaseModel):
    hits: list[SearchHit]
    users: dict[str, UserBrief]
