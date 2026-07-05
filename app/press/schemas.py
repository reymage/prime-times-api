from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PressReleaseCard(BaseModel):
    id: str
    slug: str
    title: str
    excerpt: str
    category: str
    image_url: str
    is_featured: bool
    published_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PressReleaseDetail(PressReleaseCard):
    content: str


class PressReleaseListResponse(BaseModel):
    items: list[PressReleaseCard]
    total: int
    page: int
    pages: int


class PressReleaseCreate(BaseModel):
    slug: str
    title: str
    excerpt: str = ""
    content: str = ""
    category: str = "Announcement"
    image_url: str = ""
    is_featured: bool = False
    is_published: bool = True
    published_at: datetime


class PressReleaseUpdate(BaseModel):
    slug: str | None = None
    title: str | None = None
    excerpt: str | None = None
    content: str | None = None
    category: str | None = None
    image_url: str | None = None
    is_featured: bool | None = None
    is_published: bool | None = None
    published_at: datetime | None = None
