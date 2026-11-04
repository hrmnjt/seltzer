"""Who is calling.

The Databricks Apps proxy signs people in and adds identity headers to every
request. Seltzer trusts those headers (the proxy is the only way in) and
upserts the person into `users` on first sight. Members of the configured
owner group (SELTZER_OWNER_GROUP, default "admins") become owners.

Locally, SELTZER_DEV_USER_EMAIL (or an X-Seltzer-Dev-User header) stands in
for the proxy. That path is ignored outside the local and test environments.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from starlette.concurrency import run_in_threadpool

from seltzer.config import Settings
from seltzer.db.models import User
from seltzer.domain.context import Ctx
from seltzer.domain.errors import Forbidden, Unauthorized
from seltzer.ids import uuid7

log = logging.getLogger(__name__)

EMAIL_HEADER = "x-forwarded-email"
USER_HEADER = "x-forwarded-user"
USERNAME_HEADER = "x-forwarded-preferred-username"
DEV_HEADER = "x-seltzer-dev-user"

ROLE_SYNC_EVERY = timedelta(hours=1)
SEEN_EVERY = timedelta(minutes=5)
_EMAIL_RE = re.compile(r"^[^@\s\"]+@[^@\s\"]+$")


@dataclass(frozen=True)
class Identity:
    email: str
    databricks_user_id: str | None
    display_name: str


def _name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    parts = [p for p in re.split(r"[._\-+]+", local) if p]
    return " ".join(p.capitalize() for p in parts) or email


def identity_from_headers(headers: Mapping[str, str], settings: Settings) -> Identity | None:
    email = headers.get(EMAIL_HEADER)
    user_id = headers.get(USER_HEADER)
    username = headers.get(USERNAME_HEADER)
    if not email and settings.is_local:
        email = headers.get(DEV_HEADER) or settings.seltzer_dev_user_email
        user_id = user_id or (f"dev:{email}" if email else None)
    if not email or not _EMAIL_RE.match(email):
        return None
    email = email.strip()
    name = username if username and username.lower() != email.lower() else _name_from_email(email)
    return Identity(email=email, databricks_user_id=user_id, display_name=name)


class GroupDirectory(Protocol):
    def is_member(self, email: str, group: str) -> bool: ...


class DatabricksGroupDirectory:
    """Looks up workspace group membership with the app's service principal."""

    def __init__(self) -> None:
        from databricks.sdk import WorkspaceClient

        self._client = WorkspaceClient()

    def is_member(self, email: str, group: str) -> bool:
        if not _EMAIL_RE.match(email):
            return False
        for user in self._client.users.list(
            filter=f'userName eq "{email}"', attributes="id,userName,groups"
        ):
            if any((g.display or "") == group for g in user.groups or []):
                return True
        return False


class StaticGroupDirectory:
    """Local and test stand-in: a fixed set of owner-group members."""

    def __init__(self, members: set[str]) -> None:
        self.members = {m.lower() for m in members}

    def is_member(self, email: str, group: str) -> bool:
        return email.lower() in self.members


def make_directory(settings: Settings) -> GroupDirectory:
    if settings.is_local:
        return StaticGroupDirectory(settings.dev_owner_emails)
    return DatabricksGroupDirectory()


async def resolve_user(ctx: Ctx, identity: Identity | None, directory: GroupDirectory) -> User:
    """Find or create the Seltzer user for this identity and keep their role in sync."""
    if identity is None:
        raise Unauthorized("No Databricks identity on this request")
    db = ctx.db
    user = await db.scalar(select(User).where(func.lower(User.email) == identity.email.lower()))
    changed = False
    if user is None:
        # Two first requests can race; the unique index on lower(email) settles it.
        await db.execute(
            pg_insert(User)
            .values(
                id=uuid7(),
                email=identity.email,
                databricks_user_id=identity.databricks_user_id,
                display_name=identity.display_name,
                role="member",
                last_seen_at=ctx.now,
            )
            .on_conflict_do_nothing()
        )
        user = await db.scalar(select(User).where(func.lower(User.email) == identity.email.lower()))
        assert user is not None
        changed = True
    else:
        if identity.databricks_user_id and user.databricks_user_id != identity.databricks_user_id:
            user.databricks_user_id = identity.databricks_user_id
            changed = True
        if user.last_seen_at is None or ctx.now - user.last_seen_at > SEEN_EVERY:
            user.last_seen_at = ctx.now
            changed = True

    if user.roles_synced_at is None or ctx.now - user.roles_synced_at > ROLE_SYNC_EVERY:
        try:
            in_group = await run_in_threadpool(
                directory.is_member, identity.email, ctx.settings.seltzer_owner_group
            )
        except Exception:  # directory outages must not block sign-in
            log.warning("owner group lookup failed for %s", identity.email, exc_info=True)
        else:
            # Group members are promoted; demotion is a deliberate in-app action.
            if in_group and user.role != "owner":
                user.role = "owner"
                user.active = True
            user.roles_synced_at = ctx.now
            changed = True

    if changed:
        await db.commit()
    if not user.active:
        raise Forbidden("Your Seltzer account is deactivated. Ask an admin to restore it.")
    ctx.user = user
    return user
