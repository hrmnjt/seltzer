"""Tests run against a real Postgres (TEST_PG* env vars; defaults match docker-compose)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from seltzer.config import Settings
from seltzer.db.engine import make_sync_engine
from seltzer.main import create_app
from seltzer.migrate import alembic_config

OWNER = "owner@example.com"
ADA = "ada@example.com"
BOB = "bob@example.com"
CY = "cy@example.com"

TABLES = (
    "notifications, events, reactions, attachments, comments, steps, card_tags, tags, "
    "assignments, watches, pins, cards, columns, board_watches, board_access, boards, users"
)


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return Settings(
        seltzer_env="test",
        pghost=os.environ.get("TEST_PGHOST", "localhost"),
        pgport=int(os.environ.get("TEST_PGPORT", "5432")),
        pgdatabase=os.environ.get("TEST_PGDATABASE", "seltzer_test"),
        pguser=os.environ.get("TEST_PGUSER", "seltzer"),
        pgpassword=os.environ.get("TEST_PGPASSWORD", "seltzer"),
        seltzer_dev_owner_emails=OWNER,
        seltzer_dev_user_email=None,
        seltzer_local_files_dir=str(tmp_path_factory.mktemp("files")),
        seltzer_max_upload_mb=1,
        seltzer_static_dir=str(tmp_path_factory.mktemp("static")),
    )


@pytest.fixture(scope="session")
def migrated(settings: Settings) -> None:
    """Start every session from an empty schema, exercising downgrade and upgrade."""
    from alembic import command

    engine = make_sync_engine(settings)
    with engine.begin() as conn:
        cfg = alembic_config()
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    engine.dispose()


@pytest.fixture(scope="session")
async def app(settings: Settings, migrated: None) -> AsyncIterator[Any]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture(autouse=True)
async def clean(app: Any) -> None:
    async with app.state.db.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        await conn.execute(text("ALTER SEQUENCE card_number_seq RESTART WITH 1"))
        await conn.execute(text("UPDATE workspace_settings SET default_auto_postpone_days = 30"))


class Api:
    """A signed-in client. Raises on unexpected status codes."""

    def __init__(self, app: Any, email: str) -> None:
        self.email = email
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://seltzer.test/api",
            headers={"X-Forwarded-Email": email, "X-Forwarded-User": f"id-{email}"},
        )

    async def call(
        self, method: str, url: str, expect: int | tuple[int, ...] = (200, 201, 204), **kwargs: Any
    ) -> Any:
        response = await self.http.request(method, url, **kwargs)
        codes = (expect,) if isinstance(expect, int) else expect
        assert response.status_code in codes, (
            f"{method} {url} -> {response.status_code}: {response.text}"
        )
        if response.status_code == 204 or not response.content:
            return None
        if response.headers.get("content-type", "").startswith(
            ("application/json", "application/problem+json")
        ):
            return response.json()
        return response.content

    async def get(self, url: str, **kw: Any) -> Any:
        return await self.call("GET", url, **kw)

    async def post(self, url: str, json: Any = None, **kw: Any) -> Any:
        return await self.call("POST", url, json=json, **kw)

    async def patch(self, url: str, json: Any, **kw: Any) -> Any:
        return await self.call("PATCH", url, json=json, **kw)

    async def put(self, url: str, json: Any = None, **kw: Any) -> Any:
        return await self.call("PUT", url, json=json, **kw)

    async def delete(self, url: str, **kw: Any) -> Any:
        return await self.call("DELETE", url, **kw)

    async def me(self) -> dict[str, Any]:
        return (await self.get("/me"))["user"]  # type: ignore[no-any-return]


@pytest.fixture
def as_user(app: Any) -> Callable[[str], Api]:
    return lambda email: Api(app, email)


@pytest.fixture
async def owner(as_user: Callable[[str], Api]) -> Api:
    api = as_user(OWNER)
    await api.me()
    return api


@pytest.fixture
async def ada(as_user: Callable[[str], Api]) -> Api:
    api = as_user(ADA)
    await api.me()
    return api


@pytest.fixture
async def bob(as_user: Callable[[str], Api]) -> Api:
    api = as_user(BOB)
    await api.me()
    return api


@pytest.fixture
async def cy(as_user: Callable[[str], Api]) -> Api:
    api = as_user(CY)
    await api.me()
    return api


async def make_board(
    api: Api, name: str = "Product", columns: tuple[str, ...] = ("Doing", "Review"), **kw: Any
) -> dict[str, Any]:
    body = {"name": name, "columns": [{"name": c, "color": "blue"} for c in columns], **kw}
    return await api.post("/boards", body)  # type: ignore[no-any-return]


async def make_card(
    api: Api, board_id: str, title: str = "Fix the login loop", **kw: Any
) -> dict[str, Any]:
    return (await api.post(f"/boards/{board_id}/cards", {"title": title, **kw}))["card"]  # type: ignore[no-any-return]


def doc(text_: str, mention: tuple[str, str] | None = None) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": text_}]
    if mention:
        content.append({"type": "mention", "attrs": {"id": mention[0], "label": mention[1]}})
    return {"type": "doc", "content": [{"type": "paragraph", "content": content}]}


async def age(app: Any, number: int, days: float) -> None:
    async with app.state.db.engine.begin() as conn:
        await conn.execute(
            text(
                "update cards set last_active_at = now() - make_interval(secs => :s) where number = :n"
            ),
            {"s": days * 86400, "n": number},
        )


ROOT = Path(__file__).resolve().parent
