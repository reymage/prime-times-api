from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import current_active_user
from app.auth.models import User
from app.core.roles import UserRole, role_has_at_least
from app.nav.models import NavArea, NavMenu
from app.nav.schemas import NavMenuCreate, NavMenuRead, NavMenuUpdate

router = APIRouter(prefix="/api/nav", tags=["nav"])


def _require_super_admin(current_user: User = Depends(current_active_user)) -> User:
    if not role_has_at_least(current_user.role, UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Requires super_admin role")
    return current_user


@router.get("", response_model=list[NavMenuRead])
async def list_nav_menus(area: NavArea | None = Query(None)) -> list[NavMenu]:
    qs = NavMenu.filter(is_active=True)
    if area is not None:
        qs = qs.filter(area=area)
    return await qs.order_by("position")


@router.post("", response_model=NavMenuRead, status_code=201)
async def create_nav_menu(
    body: NavMenuCreate,
    _admin: User = Depends(_require_super_admin),
) -> NavMenu:
    if await NavMenu.filter(slug=body.slug).exists():
        raise HTTPException(status_code=400, detail="A menu item with this slug already exists")
    return await NavMenu.create(**body.model_dump())


@router.patch("/{menu_id}", response_model=NavMenuRead)
async def update_nav_menu(
    menu_id: int,
    body: NavMenuUpdate,
    _admin: User = Depends(_require_super_admin),
) -> NavMenu:
    item = await NavMenu.get_or_none(id=menu_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Nav menu item not found")
    updates = body.model_dump(exclude_unset=True)
    if "slug" in updates and updates["slug"] != item.slug:
        if await NavMenu.filter(slug=updates["slug"]).exists():
            raise HTTPException(status_code=400, detail="Slug already taken")
    item.update_from_dict(updates)
    await item.save()
    return item


@router.delete("/{menu_id}", status_code=204)
async def delete_nav_menu(
    menu_id: int,
    _admin: User = Depends(_require_super_admin),
) -> None:
    item = await NavMenu.get_or_none(id=menu_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Nav menu item not found")
    await item.delete()
