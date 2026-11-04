"""The card lifecycle: Maybe?, columns, Not Now, Done, golden, drafts, ordering."""

from __future__ import annotations

from tests.conftest import Api, make_board, make_card


async def snapshot(api: Api, board_id: str) -> dict:
    return await api.get(f"/boards/{board_id}")


def lane(snap: dict, column_id: str | None) -> list[int]:
    return [c["number"] for c in snap["cards"] if c["column_id"] == column_id]


async def test_full_lifecycle(ada: Api) -> None:
    board = await make_board(ada)
    snap = await snapshot(ada, board["id"])
    doing, review = (c["id"] for c in snap["columns"])

    card = await make_card(ada, board["id"])
    assert card["number"] == 1 and card["state"] == "active" and card["column_id"] is None
    assert card["stamp"]["action"] == "published"

    n = card["number"]
    card = (await ada.post(f"/cards/{n}/triage", {"column_id": doing}))["card"]
    assert card["column_id"] == doing and card["stamp"]["action"] == "triaged"

    card = (await ada.post(f"/cards/{n}/triage", {"column_id": review}))["card"]
    assert card["column_id"] == review and card["stamp"]["action"] == "moved"

    # Closing keeps the column; reopening returns there.
    card = (await ada.post(f"/cards/{n}/close"))["card"]
    assert card["state"] == "done" and card["column_id"] == review
    card = (await ada.post(f"/cards/{n}/reopen"))["card"]
    assert card["state"] == "active" and card["column_id"] == review

    # Postponing clears the column; resuming lands in Maybe?.
    card = (await ada.post(f"/cards/{n}/postpone"))["card"]
    assert card["state"] == "not_now" and card["column_id"] is None
    assert card["closing_soon"] is False and card["auto_postpone_at"] is None
    card = (await ada.post(f"/cards/{n}/resume"))["card"]
    assert card["state"] == "active" and card["column_id"] is None

    card = (await ada.post(f"/cards/{n}/triage", {"column_id": doing}))["card"]
    card = (await ada.post(f"/cards/{n}/untriage"))["card"]
    assert card["column_id"] is None and card["stamp"]["action"] == "sent_back_to_triage"

    detail = await ada.get(f"/cards/{n}")
    actions = [e["action"] for e in reversed(detail["events"])]
    assert actions == [
        "published", "triaged", "moved", "closed", "reopened", "postponed", "resumed",
        "triaged", "sent_back_to_triage",
    ]


async def test_triage_from_not_now_and_done(ada: Api) -> None:
    board = await make_board(ada)
    doing = (await snapshot(ada, board["id"]))["columns"][0]["id"]
    a = await make_card(ada, board["id"], "A")
    await ada.post(f"/cards/{a['number']}/postpone")
    card = (await ada.post(f"/cards/{a['number']}/triage", {"column_id": doing}))["card"]
    assert card["state"] == "active" and card["column_id"] == doing

    await ada.post(f"/cards/{a['number']}/close")
    card = (await ada.post(f"/cards/{a['number']}/triage", {"column_id": doing}))["card"]
    assert card["state"] == "active"


async def test_invalid_transitions_are_conflicts(ada: Api) -> None:
    board = await make_board(ada)
    card = await make_card(ada, board["id"])
    n = card["number"]
    problem = await ada.post(f"/cards/{n}/resume", expect=409)
    assert problem["status"] == 409 and problem["current"] == "active"
    await ada.post(f"/cards/{n}/untriage", expect=409)
    await ada.post(f"/cards/{n}/close")
    await ada.post(f"/cards/{n}/close", expect=409)
    await ada.post(f"/cards/{n}/postpone", expect=409)


async def test_closing_from_not_now_reopens_into_maybe(ada: Api) -> None:
    board = await make_board(ada)
    card = await make_card(ada, board["id"])
    n = card["number"]
    await ada.post(f"/cards/{n}/postpone")
    await ada.post(f"/cards/{n}/close")
    card = (await ada.post(f"/cards/{n}/reopen"))["card"]
    assert card["state"] == "active" and card["column_id"] is None


async def test_ordering_and_golden(ada: Api) -> None:
    board = await make_board(ada)
    doing = (await snapshot(ada, board["id"]))["columns"][0]["id"]
    numbers = [(await make_card(ada, board["id"], f"Card {i}"))["number"] for i in range(4)]
    # New cards land at the top of Maybe?
    assert lane(await snapshot(ada, board["id"]), None) == list(reversed(numbers))

    cards = {c["number"]: c for c in (await snapshot(ada, board["id"]))["cards"]}
    for n in numbers:  # each to the bottom of the column, in order
        current = lane(await snapshot(ada, board["id"]), doing)
        above = cards[current[-1]]["id"] if current else None
        await ada.post(f"/cards/{n}/triage", {"column_id": doing, "above": above})
    assert lane(await snapshot(ada, board["id"]), doing) == numbers

    # Drag the last card between the first two.
    await ada.post(
        f"/cards/{numbers[3]}/triage",
        {"column_id": doing, "above": cards[numbers[0]]["id"], "below": cards[numbers[1]]["id"]},
    )
    assert lane(await snapshot(ada, board["id"]), doing) == [numbers[0], numbers[3], numbers[1], numbers[2]]

    # Golden sorts to the top and survives moves and state changes.
    await ada.put(f"/cards/{numbers[2]}/golden")
    assert lane(await snapshot(ada, board["id"]), doing)[0] == numbers[2]
    await ada.post(f"/cards/{numbers[2]}/postpone")
    card = (await ada.post(f"/cards/{numbers[2]}/resume"))["card"]
    assert card["golden"] is True
    card = (await ada.delete(f"/cards/{numbers[2]}/golden"))["card"]
    assert card["golden"] is False


async def test_drafts_are_private_until_published(ada: Api, bob: Api) -> None:
    board = await make_board(ada)
    draft = await make_card(ada, board["id"], "Half an idea", draft=True)
    assert draft["status"] == "draft"
    snap = await snapshot(ada, board["id"])
    assert snap["cards"] == [] and [d["number"] for d in snap["drafts"]] == [draft["number"]]

    await bob.get(f"/cards/{draft['number']}", expect=404)
    assert (await snapshot(bob, board["id"]))["drafts"] == []
    await ada.post(f"/cards/{draft['number']}/close", expect=409)

    card = (await ada.post(f"/cards/{draft['number']}/publish"))["card"]
    assert card["status"] == "published" and card["column_id"] is None
    assert (await bob.get(f"/cards/{draft['number']}"))["card"]["title"] == "Half an idea"


async def test_polling_versions(ada: Api, bob: Api) -> None:
    board = await make_board(ada)
    snap = await snapshot(ada, board["id"])
    version = snap["version"]
    assert await bob.get(f"/boards/{board['id']}?since={version}", expect=204) is None
    await make_card(bob, board["id"])
    fresh = await bob.get(f"/boards/{board['id']}?since={version}")
    assert fresh["version"] > version and len(fresh["cards"]) == 1


async def test_edit_conflict_and_title_events(ada: Api) -> None:
    board = await make_board(ada)
    card = await make_card(ada, board["id"])
    n, v = card["number"], card["version"]
    edited = (await ada.patch(f"/cards/{n}", {"title": "Fix the login loop for SSO", "version": v}))["card"]
    assert edited["version"] == v + 1
    problem = await ada.patch(f"/cards/{n}", {"title": "Stale", "version": v}, expect=409)
    assert problem["current_version"] == v + 1
    await ada.patch(f"/cards/{n}", {"title": "  "}, expect=422)
    detail = await ada.get(f"/cards/{n}")
    assert detail["events"][0]["action"] == "title_changed"
    assert detail["events"][0]["details"] == {"from": "Fix the login loop", "to": "Fix the login loop for SSO"}


async def test_move_card_between_boards(ada: Api) -> None:
    one = await make_board(ada, "One")
    two = await make_board(ada, "Two")
    doing = (await snapshot(ada, one["id"]))["columns"][0]["id"]
    card = await make_card(ada, one["id"])
    await ada.post(f"/cards/{card['number']}/triage", {"column_id": doing})
    moved = (await ada.patch(f"/cards/{card['number']}", {"board_id": two["id"]}))["card"]
    assert moved["board_id"] == two["id"] and moved["column_id"] is None
    assert lane(await snapshot(ada, two["id"]), None) == [card["number"]]
    assert (await snapshot(ada, one["id"]))["cards"] == []


async def test_deleting_a_column_sends_cards_to_maybe(ada: Api) -> None:
    board = await make_board(ada)
    doing = (await snapshot(ada, board["id"]))["columns"][0]["id"]
    open_card = await make_card(ada, board["id"], "Open")
    done_card = await make_card(ada, board["id"], "Done")
    for c in (open_card, done_card):
        await ada.post(f"/cards/{c['number']}/triage", {"column_id": doing})
    await ada.post(f"/cards/{done_card['number']}/close")
    await ada.delete(f"/columns/{doing}")
    snap = await snapshot(ada, board["id"])
    assert lane(snap, None) == [open_card["number"]]
    reopened = (await ada.post(f"/cards/{done_card['number']}/reopen"))["card"]
    assert reopened["column_id"] is None


async def test_deleting_a_card_keeps_its_history(ada: Api) -> None:
    board = await make_board(ada)
    card = await make_card(ada, board["id"], "Short-lived")
    await ada.delete(f"/cards/{card['number']}")
    await ada.get(f"/cards/{card['number']}", expect=404)
    page = await ada.get(f"/events?board={board['id']}")
    deleted = page["events"][0]
    assert deleted["action"] == "deleted" and deleted["card_id"] is None
    assert deleted["card_number"] == card["number"] and deleted["card_title"] == "Short-lived"


async def test_lists_and_filters(ada: Api, bob: Api) -> None:
    board = await make_board(ada)
    tag = await ada.post("/tags", {"name": "bug", "color": "red"})
    me = await bob.me()
    cards = [await make_card(ada, board["id"], f"Card {i}") for i in range(5)]
    await ada.put(f"/cards/{cards[0]['number']}/tags/{tag['id']}")
    await ada.put(f"/cards/{cards[1]['number']}/assignees/{me['id']}")
    await ada.post(f"/cards/{cards[2]['number']}/close")
    await ada.post(f"/cards/{cards[3]['number']}/postpone")

    async def numbers(query: str) -> list[int]:
        page = await ada.get(f"/boards/{board['id']}/cards?{query}")
        return [c["number"] for c in page["cards"]]

    assert await numbers("view=done") == [cards[2]["number"]]
    assert await numbers("view=not_now") == [cards[3]["number"]]
    assert await numbers(f"tag={tag['id']}") == [cards[0]["number"]]
    assert await numbers(f"assignee={me['id']}") == [cards[1]["number"]]
    assert await numbers("view=open&sort=oldest") == [cards[i]["number"] for i in (0, 1, 4)]

    first = await ada.get(f"/boards/{board['id']}/cards?view=open&limit=2")
    assert len(first["cards"]) == 2 and first["next_cursor"]
    second = await ada.get(f"/boards/{board['id']}/cards?view=open&limit=2&cursor={first['next_cursor']}")
    assert len(second["cards"]) == 1 and second["next_cursor"] is None
    summary = (await ada.get("/boards"))[0]["counts"]
    assert summary == {"maybe": 3, "open": 3, "not_now": 1, "done": 1}


async def test_steps(ada: Api) -> None:
    board = await make_board(ada)
    card = await make_card(ada, board["id"])
    n = card["number"]
    first = await ada.post(f"/cards/{n}/steps", {"body": "Reproduce"})
    second = await ada.post(f"/cards/{n}/steps", {"body": "Fix"})
    await ada.patch(f"/steps/{second['id']}", {"above": None, "below": first["id"]})
    await ada.patch(f"/steps/{first['id']}", {"completed": True})
    detail = await ada.get(f"/cards/{n}")
    assert [s["body"] for s in detail["steps"]] == ["Fix", "Reproduce"]
    assert detail["card"]["steps_done"] == 1 and detail["card"]["steps_total"] == 2
    assert detail["events"][0]["action"] == "step_completed"
