"""Fill a local Seltzer with a demo board, through the API.

    uv run python scripts/seed.py [--url http://localhost:8000]

Uses the local-only X-Seltzer-Dev-User header to act as several people, so it
only works against SELTZER_ENV=local.
"""

from __future__ import annotations

import argparse

import httpx

PEOPLE = [
    "ada@example.com",
    "grace.hopper@example.com",
    "linus@example.com",
    "katherine.j@example.com",
]


def doc(*paragraphs: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()

    def client(email: str) -> httpx.Client:
        return httpx.Client(
            base_url=f"{args.url}/api", headers={"X-Seltzer-Dev-User": email}, timeout=30
        )

    ada, grace, linus, kat = (client(e) for e in PEOPLE)
    ids = {}
    for c, email in zip((ada, grace, linus, kat), PEOPLE, strict=True):
        ids[email] = c.get("/me").raise_for_status().json()["user"]["id"]

    board = (
        ada.post(
            "/boards",
            json={
                "name": "Platform",
                "columns": [
                    {"name": "Investigating", "color": "amber"},
                    {"name": "Building", "color": "blue"},
                    {"name": "Review", "color": "violet"},
                ],
            },
        )
        .raise_for_status()
        .json()
    )
    ada.post(
        "/boards", json={"name": "Ideas", "columns": [{"name": "Exploring", "color": "teal"}]}
    ).raise_for_status()
    snap = ada.get(f"/boards/{board['id']}").raise_for_status().json()
    investigating, building, review = (c["id"] for c in snap["columns"])

    tags = {
        name: ada.post("/tags", json={"name": name, "color": color}).raise_for_status().json()["id"]
        for name, color in [
            ("bug", "red"),
            ("customer", "green"),
            ("infra", "indigo"),
            ("ux", "pink"),
        ]
    }

    def card(who: httpx.Client, title: str, description: str | None = None) -> int:
        body = {"title": title, "description": doc(description) if description else None}
        res = who.post(f"/boards/{board['id']}/cards", json=body).raise_for_status().json()
        return res["card"]["number"]

    def triage(who: httpx.Client, n: int, column: str) -> None:
        who.post(f"/cards/{n}/triage", json={"column_id": column}).raise_for_status()

    n1 = card(
        grace,
        "Login loop when the SSO session expires",
        "Users bounce between the IdP and the app.",
    )
    triage(ada, n1, building)
    ada.put(f"/cards/{n1}/tags/{tags['bug']}").raise_for_status()
    ada.put(f"/cards/{n1}/assignees/{ids[PEOPLE[2]]}").raise_for_status()
    ada.put(f"/cards/{n1}/golden").raise_for_status()
    for step in (
        "Reproduce on staging",
        "Refresh the token before redirect",
        "Add a regression test",
    ):
        linus.post(f"/cards/{n1}/steps", json={"body": step}).raise_for_status()
    linus.post(
        f"/cards/{n1}/comments",
        json={"body": doc("Reproduced: the refresh token is dropped on the second redirect.")},
    ).raise_for_status()

    n2 = card(kat, "Export a board as CSV for the quarterly review")
    kat.put(f"/cards/{n2}/tags/{tags['customer']}").raise_for_status()
    triage(grace, n2, investigating)

    n3 = card(
        linus, "Move the sweep job to serverless", "Hourly, under the app's service principal."
    )
    ada.put(f"/cards/{n3}/tags/{tags['infra']}").raise_for_status()
    triage(linus, n3, review)
    linus.put(f"/cards/{n3}/assignees/{ids[PEOPLE[2]]}").raise_for_status()

    n4 = card(ada, "Keyboard shortcuts for moving cards between columns")
    ada.put(f"/cards/{n4}/tags/{tags['ux']}").raise_for_status()
    n5 = card(grace, "Dark mode contrast on card tiles is too low")
    ada.put(f"/cards/{n5}/tags/{tags['ux']}").raise_for_status()
    card(kat, "Slack digest of what moved this week")
    n7 = card(linus, "Upgrade Postgres driver")
    triage(linus, n7, building)
    linus.post(f"/cards/{n7}/close").raise_for_status()
    n8 = card(grace, "Rewrite the importer in Rust")
    grace.post(f"/cards/{n8}/postpone").raise_for_status()
    n9 = card(ada, "Board analytics dashboard over card events")
    triage(ada, n9, investigating)
    ada.put(f"/cards/{n9}/assignees/{ids[PEOPLE[0]]}").raise_for_status()
    ada.put(f"/cards/{n9}/assignees/{ids[PEOPLE[3]]}").raise_for_status()

    grace.post(
        f"/cards/{n4}/comments", json={"body": doc("J and K to move would be lovely.")}
    ).raise_for_status()
    print(f"Seeded board {board['name']} ({board['id']}) with cards #{n1} to #{n9}")


if __name__ == "__main__":
    main()
