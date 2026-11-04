"""The hourly sweep: auto-postpone cards nobody has touched for their board's period.

Runs as a Lakeflow Job (`python -m seltzer.jobs.sweep`) against the same
database as the app and reuses the domain code, so a sweep writes the same
`auto_postponed` events a person's postpone would. A Postgres advisory lock
makes overlapping runs harmless, and the sweep only touches cards that are
still due, so a retry after a partial run is safe.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from seltzer.config import Settings, get_settings
from seltzer.db.engine import make_async_engine
from seltzer.db.models import Board, Card, WorkspaceSettings
from seltzer.domain import cards as lifecycle
from seltzer.domain.context import Ctx

log = logging.getLogger("seltzer.sweep")

SWEEP_LOCK = 0x5E17_2E5  # arbitrary, stable advisory lock key
BATCH = 200


@dataclass
class SweepResult:
    postponed: int = 0
    skipped_locked: bool = False


async def sweep(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> SweepResult:
    now = now or datetime.now(UTC)
    result = SweepResult()
    async with sessionmaker() as lock_session:
        got = await lock_session.scalar(select(func.pg_try_advisory_lock(SWEEP_LOCK)))
        if not got:
            log.info("another sweep holds the lock; exiting")
            result.skipped_locked = True
            return result
        try:
            while True:
                n = await _postpone_batch(sessionmaker, settings, now)
                result.postponed += n
                if n < BATCH:
                    break
        finally:
            await lock_session.execute(select(func.pg_advisory_unlock(SWEEP_LOCK)))
            await lock_session.commit()
    log.info("auto-postponed %d cards", result.postponed)
    return result


async def _postpone_batch(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> int:
    async with sessionmaker() as db:
        default = await db.scalar(select(WorkspaceSettings.default_auto_postpone_days)) or 30
        period_days = func.coalesce(Board.auto_postpone_days, default)
        due = (
            select(Card)
            .join(Board, Board.id == Card.board_id)
            .where(
                Card.status == "published",
                Card.state == "active",
                Board.archived_at.is_(None),
                Card.last_active_at < now - func.make_interval(0, 0, 0, period_days),
            )
            .order_by(Card.last_active_at)
            .limit(BATCH)
            .with_for_update(of=Card, skip_locked=True)
        )
        cards = list(await db.scalars(due))
        ctx = Ctx(db=db, user=None, settings=settings, now=now)
        for card in cards:
            await lifecycle.postpone(ctx, card, auto=True)
        await db.commit()
        return len(cards)


async def _main(dry_run: bool) -> int:
    settings = get_settings()
    engine = make_async_engine(settings)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        if dry_run:
            async with sessionmaker() as db:
                count = await db.scalar(text("select count(*) from cards where state = 'active'"))
                log.info("dry run: %s open cards; nothing changed", count)
            return 0
        await sweep(sessionmaker, settings)
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.dry_run)))


if __name__ == "__main__":
    main()
