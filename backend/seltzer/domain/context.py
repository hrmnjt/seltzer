"""The per-request context every domain function receives."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from seltzer.config import Settings
from seltzer.db.models import Board, User


@dataclass
class Ctx:
    db: AsyncSession
    user: User | None  # None only for system work such as the sweep job
    settings: Settings
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    _bumped: set[uuid.UUID] = field(default_factory=set)

    @property
    def me(self) -> User:
        assert self.user is not None, "this action needs a signed-in user"
        return self.user

    @property
    def is_admin(self) -> bool:
        return self.user is not None and self.user.role in ("owner", "admin")

    async def bump_board(self, board_id: uuid.UUID) -> None:
        """Advance the board's version once per transaction, so pollers see the change."""
        if board_id in self._bumped:
            return
        self._bumped.add(board_id)
        await self.db.execute(
            update(Board)
            .where(Board.id == board_id)
            .values(version=Board.version + 1, updated_at=self.now)
            .execution_options(synchronize_session=False)
        )
