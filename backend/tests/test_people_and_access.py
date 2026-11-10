"""Identity, roles, board access, notifications, comments, search and attachments."""

from __future__ import annotations

from collections.abc import Callable

from seltzer.config import Settings
from seltzer.identity import identity_from_headers
from tests.conftest import Api, doc, make_board, make_card


async def test_first_sign_in_and_owner_group(owner: Api, ada: Api) -> None:
    me = await owner.me()
    assert me["role"] == "owner" and me["email"] == "owner@example.com"
    assert (await ada.me())["role"] == "member"
    assert (await ada.me())["display_name"] == "Ada"


async def test_no_identity_is_unauthorized(as_user: Callable[[str], Api]) -> None:
    api = as_user("nobody@example.com")
    api.http.headers.pop("X-Forwarded-Email")
    problem = await api.get("/me", expect=401)
    assert problem["title"] == "Not signed in"


def test_dev_identity_only_in_local_envs() -> None:
    headers = {"x-seltzer-dev-user": "dev@example.com"}
    local = Settings(seltzer_env="local")
    prod = Settings(seltzer_env="prod", seltzer_dev_user_email="dev@example.com")
    ident = identity_from_headers(headers, local)
    assert ident is not None and ident.email == "dev@example.com"
    assert identity_from_headers(headers, prod) is None
    assert identity_from_headers({}, prod) is None
    proxied = identity_from_headers(
        {"x-forwarded-email": "grace.hopper@example.com", "x-forwarded-user": "123@456"}, prod
    )
    assert proxied is not None and proxied.display_name == "Grace Hopper"
    assert proxied.databricks_user_id == "123@456"


async def test_roles_keep_an_owner(owner: Api, ada: Api, bob: Api) -> None:
    me = await owner.me()
    ada_id = (await ada.me())["id"]
    await ada.patch(f"/users/{(await bob.me())['id']}", {"role": "admin"}, expect=403)
    await owner.patch(f"/users/{ada_id}", {"role": "admin"})
    # Admins can't mint owners, and the last owner can't step down.
    await ada.patch(f"/users/{ada_id}", {"role": "owner"}, expect=403)
    await owner.patch(f"/users/{me['id']}", {"role": "member"}, expect=409)
    # Deactivated people are locked out.
    bob_id = (await bob.me())["id"]
    await ada.patch(f"/users/{bob_id}", {"active": False})
    await bob.get("/me", expect=403)


async def test_restricted_boards(ada: Api, bob: Api, cy: Api, owner: Api) -> None:
    board = await make_board(ada, "Secret", all_access=False)
    card = await make_card(ada, board["id"])
    await bob.get(f"/boards/{board['id']}", expect=404)
    await bob.get(f"/cards/{card['number']}", expect=404)
    assert [b["name"] for b in await bob.get("/boards")] == []
    assert [b["name"] for b in await owner.get("/boards")] == ["Secret"]  # owners see everything

    bob_id = (await bob.me())["id"]
    await bob.put(f"/boards/{board['id']}/access", {"user_ids": [bob_id]}, expect=404)
    await ada.put(f"/boards/{board['id']}/access", {"user_ids": [bob_id]})
    assert (await bob.get(f"/cards/{card['number']}"))["card"]["number"] == card["number"]
    # Members can work on the board but not administer it.
    await bob.patch(f"/boards/{board['id']}", {"name": "Mine now"}, expect=403)
    # People without access can't be assigned.
    cy_id = (await cy.me())["id"]
    await ada.put(f"/cards/{card['number']}/assignees/{cy_id}", expect=422)
    hits = await cy.get("/search?q=login")
    assert hits["hits"] == []


async def test_notifications_stack_per_card(ada: Api, bob: Api, cy: Api) -> None:
    board = await make_board(ada)
    card = await make_card(ada, board["id"])  # ada watches what she files
    n = card["number"]
    cy_id = (await cy.me())["id"]
    await bob.post(f"/cards/{n}/comments", {"body": doc("Seeing this too")})
    await bob.post(f"/cards/{n}/comments", {"body": doc("And on Safari, cc ", (cy_id, "Cy"))})
    await bob.post(f"/cards/{n}/close")

    inbox = await ada.get("/notifications")
    [group] = inbox["groups"]
    assert group["card_number"] == n and group["unread"] == 3 and group["total"] == 3
    assert group["latest"]["action"] == "closed"
    assert group["actor_ids"] == [(await bob.me())["id"]]
    assert (await ada.get("/me"))["unread_notifications"] == 1

    # Cy was mentioned; Bob acted and is never notified of his own actions.
    cy_inbox = await cy.get("/notifications")
    assert cy_inbox["groups"][0]["reasons"] == ["mentioned"]
    # Bob watches since he commented, but his own close doesn't notify him.
    assert (await bob.get("/notifications"))["groups"] == []

    await ada.post("/notifications/read", {"card_ids": [card["id"]]})
    assert (await ada.get("/me"))["unread_notifications"] == 0


async def test_assignment_notifies_and_board_watchers_hear_everything(
    ada: Api, bob: Api, cy: Api
) -> None:
    board = await make_board(ada)
    await cy.put(f"/boards/{board['id']}/watch")
    card = await make_card(ada, board["id"])
    bob_id = (await bob.me())["id"]
    await ada.put(f"/cards/{card['number']}/assignees/{bob_id}")
    assert (await bob.get("/notifications"))["groups"][0]["reasons"] == ["assigned"]
    cy_group = (await cy.get("/notifications"))["groups"][0]
    assert cy_group["total"] == 2  # published + assigned


async def test_comments_reactions_and_edits(ada: Api, bob: Api) -> None:
    board = await make_board(ada)
    card = await make_card(ada, board["id"])
    comment = await bob.post(f"/cards/{card['number']}/comments", {"body": doc("First!")})
    await ada.put(f"/comments/{comment['id']}/reactions/+1")
    await bob.put(f"/comments/{comment['id']}/reactions/+1")
    await ada.patch(f"/comments/{comment['id']}", {"body": doc("Mine now")}, expect=403)
    await bob.patch(f"/comments/{comment['id']}", {"body": doc("First, edited")})
    detail = await ada.get(f"/cards/{card['number']}")
    [c] = detail["comments"]
    assert c["edited_at"] and c["reactions"][0]["count"] == 2 and c["reactions"][0]["mine"]
    bad_link = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "x",
                        "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                    }
                ],
            }
        ],
    }
    await bob.post(f"/cards/{card['number']}/comments", {"body": bad_link}, expect=422)
    await ada.delete(f"/comments/{comment['id']}")  # board admin may delete


async def test_search(ada: Api, bob: Api) -> None:
    board = await make_board(ada)
    a = await make_card(
        ada,
        board["id"],
        "Login loop on Safari",
        description=doc("Users bounce between the IdP and the app"),
    )
    b = await make_card(ada, board["id"], "Dark mode for the board")
    await bob.post(
        f"/cards/{b['number']}/comments", {"body": doc("The contrast of tiles is too low")}
    )

    async def found(q: str) -> list[int]:
        return [h["card"]["number"] for h in (await bob.get(f"/search?q={q}"))["hits"]]

    assert await found("login") == [a["number"]]
    assert await found("bouncing") == [a["number"]]  # stemmed description match
    assert await found("contrast") == [b["number"]]  # comment match
    assert await found("safarri") == [a["number"]]  # trigram typo match
    hit = (await bob.get("/search?q=contrast"))["hits"][0]
    assert "«contrast»" in hit["snippet"]


async def test_attachments(ada: Api, bob: Api, cy: Api) -> None:
    board = await make_board(ada, all_access=False)
    card = await make_card(ada, board["id"])
    files = {"file": ("../../etc/notes.txt", b"hello volume", "text/plain")}
    att = await ada.post(f"/cards/{card['number']}/attachments", files=files)
    assert att["filename"] == "notes.txt" and att["bytes"] == 12
    body = await ada.get(f"/attachments/{att['id']}")
    assert body == b"hello volume"
    await cy.get(f"/attachments/{att['id']}", expect=404)  # no board access, no bytes

    big = {"file": ("big.bin", b"x" * (1024 * 1024 + 1), "application/octet-stream")}
    await ada.post(f"/cards/{card['number']}/attachments", files=big, expect=413)
    await bob.delete(f"/attachments/{att['id']}", expect=404)
    await ada.delete(f"/attachments/{att['id']}")
    await ada.get(f"/attachments/{att['id']}", expect=404)


async def test_pins_and_timeline(ada: Api) -> None:
    board = await make_board(ada)
    one = await make_card(ada, board["id"], "One")
    two = await make_card(ada, board["id"], "Two")
    await ada.put(f"/cards/{one['number']}/pin")
    await ada.put(f"/cards/{two['number']}/pin")
    assert [c["number"] for c in await ada.get("/pins")] == [two["number"], one["number"]]
    await ada.delete(f"/cards/{two['number']}/pin")
    assert [c["number"] for c in await ada.get("/pins")] == [one["number"]]

    page = await ada.get("/events?limit=1")
    assert page["events"][0]["card_number"] == two["number"] and page["next_cursor"]
    older = await ada.get(f"/events?limit=5&before={page['next_cursor']}")
    assert [e["card_number"] for e in older["events"]] == [one["number"]]


async def test_problem_json_shape(ada: Api) -> None:
    response = await ada.http.get("/cards/999")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Not found",
        "status": 404,
        "detail": "No card #999",
    }
