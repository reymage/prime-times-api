from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import current_active_user
from app.auth.models import User
from app.core.roles import UserRole, role_has_at_least
from app.press.models import PressRelease
from app.press.schemas import (
    PressReleaseCreate,
    PressReleaseDetail,
    PressReleaseListResponse,
    PressReleaseUpdate,
)

router = APIRouter(prefix="/api/press", tags=["press"])


def _require_super_admin(current_user: User = Depends(current_active_user)) -> User:
    if not role_has_at_least(current_user.role, UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Requires super_admin role")
    return current_user


def _card(item: PressRelease) -> dict:
    return {
        "id": str(item.id),
        "slug": item.slug,
        "title": item.title,
        "excerpt": item.excerpt,
        "category": item.category,
        "image_url": item.image_url,
        "is_featured": item.is_featured,
        "published_at": item.published_at,
    }


@router.get("", response_model=PressReleaseListResponse)
async def list_press_releases(
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50),
    category: str | None = Query(None),
):
    qs = PressRelease.filter(is_published=True)
    if category:
        qs = qs.filter(category__iexact=category)
    total = await qs.count()
    items = await qs.order_by("-published_at").offset((page - 1) * limit).limit(limit)
    pages = max(1, (total + limit - 1) // limit)
    return {"items": [_card(i) for i in items], "total": total, "page": page, "pages": pages}


@router.get("/{slug}", response_model=PressReleaseDetail)
async def get_press_release(slug: str):
    item = await PressRelease.get_or_none(slug=slug, is_published=True)
    if item is None:
        raise HTTPException(status_code=404, detail="Press release not found")
    return {**_card(item), "content": item.content}


@router.post("", response_model=PressReleaseDetail, status_code=201)
async def create_press_release(
    body: PressReleaseCreate,
    _admin: User = Depends(_require_super_admin),
):
    if await PressRelease.filter(slug=body.slug).exists():
        raise HTTPException(status_code=400, detail="A press release with this slug already exists")
    item = await PressRelease.create(**body.model_dump())
    return {**_card(item), "content": item.content}


@router.patch("/{slug}", response_model=PressReleaseDetail)
async def update_press_release(
    slug: str,
    body: PressReleaseUpdate,
    _admin: User = Depends(_require_super_admin),
):
    item = await PressRelease.get_or_none(slug=slug)
    if item is None:
        raise HTTPException(status_code=404, detail="Press release not found")
    updates = body.model_dump(exclude_unset=True)
    if "slug" in updates and updates["slug"] != item.slug:
        if await PressRelease.filter(slug=updates["slug"]).exists():
            raise HTTPException(status_code=400, detail="Slug already taken")
    item.update_from_dict(updates)
    await item.save()
    return {**_card(item), "content": item.content}


@router.delete("/{slug}", status_code=204)
async def delete_press_release(
    slug: str,
    _admin: User = Depends(_require_super_admin),
) -> None:
    item = await PressRelease.get_or_none(slug=slug)
    if item is None:
        raise HTTPException(status_code=404, detail="Press release not found")
    await item.delete()
