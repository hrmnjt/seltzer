"""Auto-postpone: the hourly sweep and the "closing soon" warning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from seltzer.jobs.sweep import SWEEP_LOCK, sweep
from tests.conftest import Api, make_board, make_card


async def age(app: Any, number: int, days: float) -> None:
    async with app.state.db.engine.begin() as conn:
        await conn.execute(
            text(
                "update cards set last_active_at = now() - make_interval(secs => :s) where number = :n"
            ),
            {"s": days * 86400, "n": number},
        )


async def test_sweep_postpones_idle_cards(app: Any, ada: Api, bob: Api) -> None:
    board = await make_board(ada)
    doing = (await ada.get(f"/boards/{board['id']}"))["columns"][0]["id"]
    idle = await make_card(ada, board["id"], "Idle")
    busy = await make_card(ada, board["id"], "Busy")
    await ada.post(f"/cards/{idle['number']}/triage", {"column_id": doing})
    await bob.post(
        f"/cards/{idle['number']}/comments",
        {
            "body": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "ping"}]}],
            }
        },
    )
    await age(app, idle["number"], 31)
    await age(app, busy["number"], 10)

    result = await sweep(app.state.db.sessionmaker, app.state.settings)
    assert result.postponed == 1

    card = (await ada.get(f"/cards/{idle['number']}"))["card"]
    assert card["state"] == "not_now" and card["column_id"] is None and card["auto_postponed"]
    assert card["state_changed_by"] is None
    event = (await ada.get(f"/cards/{idle['number']}"))["events"][0]
    assert event["action"] == "auto_postponed" and event["actor_id"] is None
    # Watchers hear about it (Bob commented, so he watches).
    assert (await bob.get("/notifications"))["groups"][0]["latest"]["action"] == "auto_postponed"

    # Running again finds nothing new.
    assert (await sweep(app.state.db.sessionmaker, app.state.settings)).postponed == 0


async def test_board_period_and_closing_soon(app: Any, ada: Api) -> None:
    board = await make_board(ada, auto_postpone_days=7)
    card = await make_card(ada, board["id"])
    await age(app, card["number"], 6)  # 6/7 > 75%
    tile = (await ada.get(f"/boards/{board['id']}"))["cards"][0]
    assert tile["closing_soon"] is True
    page = await ada.get(f"/boards/{board['id']}/cards?view=closing_soon")
    assert [c["number"] for c in page["cards"]] == [card["number"]]

    later = datetime.now(UTC) + timedelta(days=2)
    result = await sweep(app.state.db.sessionmaker, app.state.settings, now=later)
    assert result.postponed == 1

    # Resetting the board to the workspace default (30 days) stops the clock again.
    await ada.patch(f"/boards/{board['id']}", {"auto_postpone_days": None})
    summary = (await ada.get("/boards"))[0]
    assert summary["effective_auto_postpone_days"] == 30 and summary["auto_postpone_days"] is None


async def test_touching_resets_the_clock(app: Any, ada: Api) -> None:
    board = await make_board(ada)
    card = await make_card(ada, board["id"])
    await age(app, card["number"], 29)
    await ada.post(f"/cards/{card['number']}/steps", {"body": "Still on it"})
    assert (await sweep(app.state.db.sessionmaker, app.state.settings)).postponed == 0
    tile = (await ada.get(f"/boards/{board['id']}"))["cards"][0]
    assert tile["closing_soon"] is False


async def test_overlapping_sweeps_skip(app: Any, ada: Api) -> None:
    async with app.state.db.sessionmaker() as other:
        assert await other.scalar(select(func.pg_try_advisory_lock(SWEEP_LOCK)))
        try:
            result = await sweep(app.state.db.sessionmaker, app.state.settings)
            assert result.skipped_locked
        finally:
            await other.scalar(select(func.pg_advisory_unlock(SWEEP_LOCK)))


def test_migration_grants_roles(settings: Any) -> None:
    """Granting is idempotent and quotes the role; here the test role grants to itself."""
    from seltzer.db.engine import make_sync_engine
    from seltzer.migrate import grant

    engine = make_sync_engine(settings)
    with engine.begin() as conn:
        grant(conn, settings.pguser)
        assert conn.execute(
            text("select has_table_privilege(current_user, 'cards', 'UPDATE')")
        ).scalar()
    engine.dispose()
