from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, model_validator


def _time_ago(dt: datetime) -> str:
    now = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return "just now"
    m = secs // 60
    if m < 60:
        return f"{m}m ago"
    h = m // 60
    if h < 24:
        return f"{h}h ago"
    d = h // 24
    if d < 7:
        return f"{d}d ago"
    w = d // 7
    if w < 5:
        return f"{w}w ago"
    mo = d // 30
    if mo < 12:
        return f"{mo} months ago"
    return f"{d // 365} years ago"


class ArticleCard(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    excerpt: str
    key_points: list[str] | None = None
    category: str
    image_url: str
    author: str
    source: str
    source_icon: str | None = None
    source_url: str | None = None
    is_video: bool = False
    video_url: str | None = None
    is_internal: bool = False
    is_featured: bool = False
    is_premium: bool = False
    is_editorial_pick: bool = False
    view_count: int = 0
    author_avatar: str | None = None
    published_at: datetime
    time_ago: str = ""
    tags: list[str] = []
    issue_cluster_slug: str | None = None
    issue_cluster_name: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def fill_time_ago(self) -> "ArticleCard":
        if not self.time_ago:
            self.time_ago = _time_ago(self.published_at)
        return self


class ArticleDetail(ArticleCard):
    content: str = ""
    related: list[ArticleCard] = []


class FeedResponse(BaseModel):
    articles: list[ArticleCard]
    total: int
    page: int
    pages: int
    personalized: bool = False


class FeedbackIn(BaseModel):
    # "Did this story help you understand the issue?" — true = yes, false = no.
    helpful: bool
