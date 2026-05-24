from pydantic import BaseModel, ConfigDict

from app.nav.models import NavArea, NavItemType


class NavMenuRead(BaseModel):
    id: int
    label: str
    slug: str
    href: str | None = None
    area: NavArea
    item_type: NavItemType
    position: int
    is_active: bool
    roles: list[str] | None = None

    model_config = ConfigDict(from_attributes=True)


class NavMenuCreate(BaseModel):
    label: str
    slug: str
    href: str | None = None
    area: NavArea = NavArea.main
    item_type: NavItemType = NavItemType.primary
    position: int = 0
    roles: list[str] | None = None


class NavMenuUpdate(BaseModel):
    label: str | None = None
    slug: str | None = None
    href: str | None = None
    area: NavArea | None = None
    item_type: NavItemType | None = None
    position: int | None = None
    is_active: bool | None = None
    roles: list[str] | None = None
