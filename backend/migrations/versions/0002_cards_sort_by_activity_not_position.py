"""cards sort by activity, not position

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08 05:19:30.469824
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Lanes now list golden cards first, then the most recently active, as Fizzy does:
    # a card dropped on a lane lands on top and nothing is placed by hand.
    op.drop_index(op.f("ix_cards_board_state"), table_name="cards")
    op.create_index(
        "ix_cards_board_state",
        "cards",
        ["board_id", "state", "column_id", "last_active_at"],
        unique=False,
    )
    op.drop_column("cards", "position")


def downgrade() -> None:
    op.add_column(
        "cards",
        sa.Column("position", sa.VARCHAR(collation="C"), nullable=False, server_default="V"),
    )
    op.alter_column("cards", "position", server_default=None)
    op.drop_index("ix_cards_board_state", table_name="cards")
    op.create_index(
        op.f("ix_cards_board_state"),
        "cards",
        ["board_id", "state", "column_id", "position"],
        unique=False,
    )
