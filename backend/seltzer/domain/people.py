"""Workspace people, roles, settings and tags."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from seltzer.db.models import Tag, User, WorkspaceSettings
from seltzer.domain.boards import COLUMN_COLORS
from seltzer.domain.context import Ctx
from seltzer.domain.errors import Conflict, Forbidden, Invalid, NotFound


async def list_users(ctx: Ctx, q: str | None = None, include_inactive: bool = False) -> list[User]:
    stmt = select(User).order_by(func.lower(User.display_name))
    if not include_inactive:
        stmt = stmt.where(User.active)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(User.display_name).like(like) | func.lower(User.email).like(like)
        )
    return list(await ctx.db.scalars(stmt.limit(200)))


async def update_user(
    ctx: Ctx, user_id: uuid.UUID, *, role: str | None, active: bool | None
) -> User:
    """Admins manage members and admins; only owners touch owners."""
    if not ctx.is_admin:
        raise Forbidden("Only admins can manage people")
    target = await ctx.db.get(User, user_id, with_for_update=True)
    if target is None:
        raise NotFound("No such person")
    me_owner = ctx.me.role == "owner"
    if (target.role == "owner" or role == "owner") and not me_owner:
        raise Forbidden("Only owners can grant or change the owner role")
    losing_owner = target.role == "owner" and (
        (role is not None and role != "owner") or active is False
    )
    if losing_owner:
        owners = await ctx.db.scalar(
            select(func.count()).where(User.role == "owner", User.active, User.id != target.id)
        )
        if not owners:
            raise Conflict("Seltzer needs at least one active owner")
    if role is not None:
        target.role = role
    if active is not None:
        target.active = active
    return target


async def get_settings(ctx: Ctx) -> WorkspaceSettings:
    row = await ctx.db.get(WorkspaceSettings, 1)
    assert row is not None, "migration seeds the settings row"
    return row


async def update_settings(ctx: Ctx, default_auto_postpone_days: int) -> WorkspaceSettings:
    if not ctx.is_admin:
        raise Forbidden("Only admins can change workspace settings")
    row = await get_settings(ctx)
    row.default_auto_postpone_days = default_auto_postpone_days
    return row


def _tag_name(name: str) -> str:
    name = " ".join(name.split()).lstrip("#")
    if not name or len(name) > 40:
        raise Invalid("Tag names need 1 to 40 characters")
    return name


def _tag_color(color: str) -> str:
    if color not in COLUMN_COLORS:
        raise Invalid(f"Tag colours are one of: {', '.join(COLUMN_COLORS)}")
    return color


async def create_tag(ctx: Ctx, name: str, color: str) -> Tag:
    name = _tag_name(name)
    existing = await ctx.db.scalar(select(Tag).where(func.lower(Tag.name) == name.lower()))
    if existing is not None:
        return existing
    tag = Tag(name=name, color=_tag_color(color), created_at=ctx.now)
    ctx.db.add(tag)
    await ctx.db.flush()
    return tag


async def update_tag(ctx: Ctx, tag_id: uuid.UUID, name: str | None, color: str | None) -> Tag:
    if not ctx.is_admin:
        raise Forbidden("Only admins can rename or recolour tags")
    tag = await ctx.db.get(Tag, tag_id)
    if tag is None:
        raise NotFound("No such tag")
    if name is not None:
        tag.name = _tag_name(name)
    if color is not None:
        tag.color = _tag_color(color)
    return tag


async def delete_tag(ctx: Ctx, tag_id: uuid.UUID) -> None:
    if not ctx.is_admin:
        raise Forbidden("Only admins can delete tags")
    tag = await ctx.db.get(Tag, tag_id)
    if tag is None:
        raise NotFound("No such tag")
    await ctx.db.delete(tag)
