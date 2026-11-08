"""SQLAlchemy models. The Alembic migrations are the source of truth for DDL
details the ORM doesn't express (generated tsvector columns, trigram indexes)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Sequence,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from seltzer.ids import uuid7

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Fractional-index keys compare bytewise.
Position = String(collation="C")

card_number_seq = Sequence("card_number_seq", start=1)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {
        uuid.UUID: UUID(as_uuid=True),
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid7)


def created() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role in ('owner', 'admin', 'member')", name="role"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    databricks_user_id: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="member", server_default="member")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    last_seen_at: Mapped[datetime | None]
    roles_synced_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()


class WorkspaceSettings(Base):
    __tablename__ = "workspace_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("default_auto_postpone_days between 3 and 365", name="period"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    default_auto_postpone_days: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30"
    )


class Board(Base):
    __tablename__ = "boards"
    __table_args__ = (
        CheckConstraint(
            "auto_postpone_days is null or auto_postpone_days between 3 and 365", name="period"
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(Text)
    all_access: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    auto_postpone_days: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None]
    # Bumped by every write that changes what the board screen shows.
    version: Mapped[int] = mapped_column(BigInteger, default=1, server_default="1")
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class BoardAccess(Base):
    """The access list of a restricted board. All-access boards have no rows."""

    __tablename__ = "board_access"

    board_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = created()


class BoardWatch(Base):
    __tablename__ = "board_watches"

    board_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = created()


class Column(Base):
    __tablename__ = "columns"

    id: Mapped[uuid.UUID] = pk()
    board_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text)
    position: Mapped[str] = mapped_column(Position)
    created_at: Mapped[datetime] = created()


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("status in ('draft', 'published')", name="status"),
        CheckConstraint("state in ('active', 'not_now', 'done')", name="state"),
        CheckConstraint("state <> 'not_now' or column_id is null", name="not_now_has_no_column"),
        CheckConstraint("status = 'published' or column_id is null", name="draft_has_no_column"),
        # Lanes list golden cards first, then the most recently active.
        Index("ix_cards_board_state", "board_id", "state", "column_id", "last_active_at"),
        Index(
            "ix_cards_sweep",
            "last_active_at",
            postgresql_where=text("status = 'published' and state = 'active'"),
        ),
        Index("ix_cards_search", "search", postgresql_using="gin"),
        Index(
            "ix_cards_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    number: Mapped[int] = mapped_column(
        BigInteger, card_number_seq, server_default=card_number_seq.next_value(), unique=True
    )
    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"))
    column_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("columns.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[dict[str, Any] | None]
    description_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(Text, default="published")
    state: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    state_changed_at: Mapped[datetime | None]
    state_changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    auto_postponed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    golden_at: Mapped[datetime | None]
    last_active_at: Mapped[datetime] = mapped_column(server_default=func.now())
    published_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Optimistic concurrency for edits: PATCH may send the version it read.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    search: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english'::regconfig, coalesce(description_text, '')), 'B')",
            persisted=True,
        ),
        deferred=True,
    )


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[uuid.UUID] = pk()
    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    position: Mapped[str] = mapped_column(Position)
    completed_at: Mapped[datetime | None]
    completed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created()


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (Index("uq_tags_name_lower", text("lower(name)"), unique=True),)

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()


class CardTag(Base):
    __tablename__ = "card_tags"

    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Assignment(Base):
    __tablename__ = "assignments"

    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created()


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_search", "search", postgresql_using="gin"),)

    id: Mapped[uuid.UUID] = pk()
    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[dict[str, Any]]
    body_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    edited_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()
    search: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english'::regconfig, coalesce(body_text, ''))", persisted=True),
        deferred=True,
    )


class Reaction(Base):
    __tablename__ = "reactions"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    emoji: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = created()


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = pk()
    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="SET NULL")
    )
    volume_path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    bytes: Mapped[int] = mapped_column(BigInteger)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created()


class Event(Base):
    """Append-only log behind stamps, the timeline, notifications and analytics."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_board_id_id", "board_id", text("id desc")),
        Index("ix_events_card_id_id", "card_id", text("id desc")),
    )

    id: Mapped[uuid.UUID] = pk()
    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"))
    # SET NULL keeps history (and analytics) when a card is deleted.
    card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cards.id", ondelete="SET NULL"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))  # null = Seltzer
    action: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = created()


class Watch(Base):
    __tablename__ = "watches"

    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = created()


class Pin(Base):
    __tablename__ = "pins"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[str] = mapped_column(Position)
    created_at: Mapped[datetime] = created()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("reason in ('watching', 'assigned', 'mentioned')", name="reason"),
        Index("ix_notifications_inbox", "user_id", "card_id", text("id desc")),
        Index("ix_notifications_unread", "user_id", postgresql_where=text("read_at is null")),
    )

    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()
