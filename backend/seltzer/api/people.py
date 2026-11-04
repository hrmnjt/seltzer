"""/api/me, people, workspace settings and tags."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from seltzer.api.deps import get_ctx
from seltzer.api.schemas import (
    MeOut,
    SettingsOut,
    SettingsPatch,
    TagIn,
    TagOut,
    TagPatch,
    UserOut,
    UserPatch,
)
from seltzer.domain import people, queries
from seltzer.domain.context import Ctx

router = APIRouter(tags=["people"])


@router.get("/me")
async def me(ctx: Ctx = Depends(get_ctx)) -> MeOut:
    return MeOut(
        user=UserOut.model_validate(ctx.me),
        unread_notifications=await queries.unread_count(ctx),
        workspace_default_auto_postpone_days=await queries.workspace_default(ctx),
    )


@router.get("/users")
async def list_users(
    q: str | None = None, include_inactive: bool = False, ctx: Ctx = Depends(get_ctx)
) -> list[UserOut]:
    users = await people.list_users(ctx, q, include_inactive and ctx.is_admin)
    return [UserOut.model_validate(u) for u in users]


@router.patch("/users/{user_id}")
async def update_user(user_id: uuid.UUID, body: UserPatch, ctx: Ctx = Depends(get_ctx)) -> UserOut:
    user = await people.update_user(ctx, user_id, role=body.role, active=body.active)
    out = UserOut.model_validate(user)
    await ctx.db.commit()
    return out


@router.get("/settings")
async def get_settings(ctx: Ctx = Depends(get_ctx)) -> SettingsOut:
    return SettingsOut.model_validate(await people.get_settings(ctx))


@router.patch("/settings")
async def update_settings(body: SettingsPatch, ctx: Ctx = Depends(get_ctx)) -> SettingsOut:
    row = await people.update_settings(ctx, body.default_auto_postpone_days)
    out = SettingsOut.model_validate(row)
    await ctx.db.commit()
    return out


@router.get("/tags")
async def list_tags(ctx: Ctx = Depends(get_ctx)) -> list[TagOut]:
    from sqlalchemy import select

    from seltzer.db.models import Tag

    return [TagOut.model_validate(t) for t in await ctx.db.scalars(select(Tag).order_by(Tag.name))]


@router.post("/tags", status_code=201)
async def create_tag(body: TagIn, ctx: Ctx = Depends(get_ctx)) -> TagOut:
    tag = await people.create_tag(ctx, body.name, body.color)
    out = TagOut.model_validate(tag)
    await ctx.db.commit()
    return out


@router.patch("/tags/{tag_id}")
async def update_tag(tag_id: uuid.UUID, body: TagPatch, ctx: Ctx = Depends(get_ctx)) -> TagOut:
    tag = await people.update_tag(ctx, tag_id, body.name, body.color)
    out = TagOut.model_validate(tag)
    await ctx.db.commit()
    return out


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(tag_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    await people.delete_tag(ctx, tag_id)
    await ctx.db.commit()
    return Response(status_code=204)
