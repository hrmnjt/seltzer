"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-04 15:04:49.732459
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pg_trgm powers typo-tolerant title search. Lakebase supports it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # Card numbers are workspace-wide, for URLs like /cards/42.
    op.execute("CREATE SEQUENCE card_number_seq START 1")
    op.create_table(
        "tags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
    )
    op.create_index("uq_tags_name_lower", "tags", [sa.literal_column("lower(name)")], unique=True)
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("databricks_user_id", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), server_default="member", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("roles_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role in ('owner', 'admin', 'member')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("databricks_user_id", name=op.f("uq_users_databricks_user_id")),
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "workspace_settings",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("default_auto_postpone_days", sa.Integer(), server_default="30", nullable=False),
        sa.CheckConstraint(
            "default_auto_postpone_days between 3 and 365",
            name=op.f("ck_workspace_settings_period"),
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_workspace_settings_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_settings")),
    )
    op.create_table(
        "boards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("all_access", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("auto_postpone_days", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "auto_postpone_days is null or auto_postpone_days between 3 and 365",
            name=op.f("ck_boards_period"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_boards_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boards")),
    )
    op.create_table(
        "board_access",
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["boards.id"],
            name=op.f("fk_board_access_board_id_boards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_board_access_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("board_id", "user_id", name=op.f("pk_board_access")),
    )
    op.create_index(op.f("ix_board_access_user_id"), "board_access", ["user_id"], unique=False)
    op.create_table(
        "board_watches",
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["boards.id"],
            name=op.f("fk_board_watches_board_id_boards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_board_watches_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("board_id", "user_id", name=op.f("pk_board_watches")),
    )
    op.create_table(
        "columns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column("position", sa.String(collation="C"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], name=op.f("fk_columns_board_id_boards"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_columns")),
    )
    op.create_index(op.f("ix_columns_board_id"), "columns", ["board_id"], unique=False)
    op.create_table(
        "cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "number",
            sa.BigInteger(),
            server_default=sa.text("nextval('card_number_seq')"),
            nullable=False,
        ),
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("column_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description_text", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="active", nullable=False),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_changed_by", sa.UUID(), nullable=True),
        sa.Column("auto_postponed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("golden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.String(collation="C"), nullable=False),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A') || setweight(to_tsvector('english'::regconfig, coalesce(description_text, '')), 'B')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state <> 'not_now' or column_id is null", name=op.f("ck_cards_not_now_has_no_column")
        ),
        sa.CheckConstraint("state in ('active', 'not_now', 'done')", name=op.f("ck_cards_state")),
        sa.CheckConstraint(
            "status = 'published' or column_id is null", name=op.f("ck_cards_draft_has_no_column")
        ),
        sa.CheckConstraint("status in ('draft', 'published')", name=op.f("ck_cards_status")),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], name=op.f("fk_cards_board_id_boards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["column_id"],
            ["columns.id"],
            name=op.f("fk_cards_column_id_columns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_cards_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["state_changed_by"], ["users.id"], name=op.f("fk_cards_state_changed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cards")),
        sa.UniqueConstraint("number", name=op.f("uq_cards_number")),
    )
    op.create_index(
        "ix_cards_board_state",
        "cards",
        ["board_id", "state", "column_id", "position"],
        unique=False,
    )
    op.create_index("ix_cards_search", "cards", ["search"], unique=False, postgresql_using="gin")
    op.create_index(
        "ix_cards_sweep",
        "cards",
        ["last_active_at"],
        unique=False,
        postgresql_where=sa.text("status = 'published' and state = 'active'"),
    )
    op.create_table(
        "assignments",
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("assigned_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"], ["users.id"], name=op.f("fk_assignments_assigned_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_assignments_card_id_cards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_assignments_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("card_id", "user_id", name=op.f("pk_assignments")),
    )
    op.create_index(op.f("ix_assignments_user_id"), "assignments", ["user_id"], unique=False)
    op.create_table(
        "card_tags",
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_card_tags_card_id_cards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_card_tags_tag_id_tags"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("card_id", "tag_id", name=op.f("pk_card_tags")),
    )
    op.create_index(op.f("ix_card_tags_tag_id"), "card_tags", ["tag_id"], unique=False)
    op.create_table(
        "comments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("body_text", sa.Text(), server_default="", nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english'::regconfig, coalesce(body_text, ''))", persisted=True
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_comments_author_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_comments_card_id_cards"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index(op.f("ix_comments_card_id"), "comments", ["card_id"], unique=False)
    op.create_index(
        "ix_comments_search", "comments", ["search"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_events_actor_id_users")),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], name=op.f("fk_events_board_id_boards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_events_card_id_cards"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index(
        "ix_events_board_id_id", "events", ["board_id", sa.literal_column("id desc")], unique=False
    )
    op.create_index(
        "ix_events_card_id_id", "events", ["card_id", sa.literal_column("id desc")], unique=False
    )
    op.create_table(
        "pins",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.String(collation="C"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_pins_card_id_cards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_pins_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "card_id", name=op.f("pk_pins")),
    )
    op.create_table(
        "steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("position", sa.String(collation="C"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_steps_card_id_cards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["completed_by"], ["users.id"], name=op.f("fk_steps_completed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_steps")),
    )
    op.create_index(op.f("ix_steps_card_id"), "steps", ["card_id"], unique=False)
    op.create_table(
        "watches",
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_watches_card_id_cards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_watches_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("card_id", "user_id", name=op.f("pk_watches")),
    )
    op.create_index(op.f("ix_watches_user_id"), "watches", ["user_id"], unique=False)
    op.create_table(
        "attachments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("comment_id", sa.UUID(), nullable=True),
        sa.Column("volume_path", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_attachments_card_id_cards"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["comments.id"],
            name=op.f("fk_attachments_comment_id_comments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_attachments_uploaded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
    )
    op.create_index(op.f("ix_attachments_card_id"), "attachments", ["card_id"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason in ('watching', 'assigned', 'mentioned')", name=op.f("ck_notifications_reason")
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["cards.id"],
            name=op.f("fk_notifications_card_id_cards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_notifications_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        "ix_notifications_inbox",
        "notifications",
        ["user_id", "card_id", sa.literal_column("id desc")],
        unique=False,
    )
    op.create_index(
        "ix_notifications_unread",
        "notifications",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("read_at is null"),
    )
    op.create_table(
        "reactions",
        sa.Column("comment_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("emoji", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["comments.id"],
            name=op.f("fk_reactions_comment_id_comments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_reactions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("comment_id", "user_id", "emoji", name=op.f("pk_reactions")),
    )
    op.execute("CREATE INDEX ix_cards_title_trgm ON cards USING gin (title gin_trgm_ops)")
    op.execute("ALTER SEQUENCE card_number_seq OWNED BY cards.number")
    op.execute("INSERT INTO workspace_settings (id, default_auto_postpone_days) VALUES (1, 30)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cards_title_trgm")
    op.drop_table("reactions")
    op.drop_index(
        "ix_notifications_unread",
        table_name="notifications",
        postgresql_where=sa.text("read_at is null"),
    )
    op.drop_index("ix_notifications_inbox", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_attachments_card_id"), table_name="attachments")
    op.drop_table("attachments")
    op.drop_index(op.f("ix_watches_user_id"), table_name="watches")
    op.drop_table("watches")
    op.drop_index(op.f("ix_steps_card_id"), table_name="steps")
    op.drop_table("steps")
    op.drop_table("pins")
    op.drop_index("ix_events_card_id_id", table_name="events")
    op.drop_index("ix_events_board_id_id", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_comments_search", table_name="comments", postgresql_using="gin")
    op.drop_index(op.f("ix_comments_card_id"), table_name="comments")
    op.drop_table("comments")
    op.drop_index(op.f("ix_card_tags_tag_id"), table_name="card_tags")
    op.drop_table("card_tags")
    op.drop_index(op.f("ix_assignments_user_id"), table_name="assignments")
    op.drop_table("assignments")
    op.drop_index(
        "ix_cards_sweep",
        table_name="cards",
        postgresql_where=sa.text("status = 'published' and state = 'active'"),
    )
    op.drop_index("ix_cards_search", table_name="cards", postgresql_using="gin")
    op.drop_index("ix_cards_board_state", table_name="cards")
    op.drop_table("cards")
    op.drop_index(op.f("ix_columns_board_id"), table_name="columns")
    op.drop_table("columns")
    op.drop_table("board_watches")
    op.drop_index(op.f("ix_board_access_user_id"), table_name="board_access")
    op.drop_table("board_access")
    op.drop_table("boards")
    op.drop_table("workspace_settings")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_index("uq_tags_name_lower", table_name="tags")
    op.drop_table("tags")
