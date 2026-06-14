import html
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.console.models import ConsoleStoryStatus, IssueClusterStatus

# ── HTML sanitizer ────────────────────────────────────────────────────────────

_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_ON_ATTR_RE = re.compile(r'\s+on\w+\s*=\s*(?:"[^"]*"|\'[^\']*\'|\S+)', re.IGNORECASE)
_JS_HREF_RE = re.compile(
    r'(href|src|action)\s*=\s*(?:"javascript:[^"]*"|\'javascript:[^\']*\')',
    re.IGNORECASE,
)

ALLOWED_IFRAME_DOMAINS = frozenset([
    "www.youtube.com",
    "youtube.com",
    "www.youtube-nocookie.com",
    "youtube-nocookie.com",
    "player.vimeo.com",
    "vimeo.com",
    "platform.twitter.com",
])

_IFRAME_SRC_RE = re.compile(r'<iframe[^>]+src\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def _sanitize_html(raw: str) -> str:
    """Strip dangerous HTML patterns. Not a full parser — defence in depth."""
    if not raw:
        return ""
    s = _SCRIPT_RE.sub("", raw)
    s = _STYLE_RE.sub("", s)
    s = _ON_ATTR_RE.sub("", s)
    s = _JS_HREF_RE.sub("", s)

    # Remove iframes pointing to non-whitelisted domains
    def _check_iframe(m: re.Match) -> str:
        src = m.group(1)
        from urllib.parse import urlparse
        try:
            host = urlparse(src).netloc.lower()
        except Exception:
            return ""
        return m.group(0) if host in ALLOWED_IFRAME_DOMAINS else ""

    s = _IFRAME_SRC_RE.sub(_check_iframe, s)
    return s.strip()


# ── Section schema ─────────────────────────────────────────────────────────────

class SectionData(BaseModel):
    id: str
    type: str = "text"  # text | image | video | chart
    # Text section
    heading: str = ""
    content: str = ""
    # Image section
    src: str = ""
    alt: str = ""
    caption: str = ""
    # Video section (YouTube / Vimeo)
    provider: str = ""
    video_id: str = ""
    # Chart section
    chart_type: str = "bar"
    chart_title: str = ""
    chart_data: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("content", mode="before")
    @classmethod
    def sanitize_content(cls, v: object) -> str:
        return _sanitize_html(str(v)) if v else ""

    @field_validator("heading", "alt", "caption", "chart_title", mode="before")
    @classmethod
    def escape_plain(cls, v: object) -> str:
        return html.escape(str(v)[:500]) if v else ""

    @field_validator("src", mode="before")
    @classmethod
    def validate_src(cls, v: object) -> str:
        s = str(v).strip() if v else ""
        if s.lower().startswith("javascript:"):
            return ""
        return s[:500]

    @field_validator("provider", mode="before")
    @classmethod
    def validate_provider(cls, v: object) -> str:
        return str(v) if v in ("youtube", "vimeo") else ""

    @field_validator("chart_type", mode="before")
    @classmethod
    def validate_chart_type(cls, v: object) -> str:
        return str(v) if v in ("bar", "line", "pie", "area") else "bar"


# ── Story schemas ──────────────────────────────────────────────────────────────

class ConsoleStoryCreate(BaseModel):
    title: str = Field(default="", max_length=500)
    standfirst: str = Field(default="")
    sections: list[SectionData] = Field(default_factory=list)
    cover_image: Optional[str] = Field(default=None, max_length=500)
    category: str = Field(default="", max_length=100)
    tags: list[str] = Field(default_factory=list)
    story_type: str = Field(default="article", max_length=50)
    status: ConsoleStoryStatus = Field(default=ConsoleStoryStatus.auto_draft)
    scheduled_for: Optional[str] = None
    word_count: int = Field(default=0, ge=0)
    editor_note: Optional[str] = None
    geo_regions: list[str] = Field(default_factory=list)
    is_featured: bool = False
    is_editorial_pick: bool = False
    issue_cluster_id: Optional[str] = None

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v: object) -> str:
        return html.escape(str(v)[:500]) if v else ""

    @field_validator("standfirst", mode="before")
    @classmethod
    def sanitize_standfirst(cls, v: object) -> str:
        return _sanitize_html(str(v)[:2000]) if v else ""

    @field_validator("story_type", mode="before")
    @classmethod
    def validate_type(cls, v: object) -> str:
        valid = {"article", "video", "research_note", "fact_check", "contextual_tile"}
        return str(v) if str(v) in valid else "article"

    @field_validator("tags", mode="before")
    @classmethod
    def sanitize_tags(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [html.escape(str(t)[:100]) for t in v[:20]]
        return []

    @field_validator("cover_image", mode="before")
    @classmethod
    def validate_cover(cls, v: object) -> Optional[str]:
        if not v:
            return None
        s = str(v).strip()
        if s.lower().startswith("javascript:"):
            return None
        return s[:500]

    @field_validator("sections", mode="before")
    @classmethod
    def cap_sections(cls, v: object) -> list:
        if isinstance(v, list):
            return v[:200]
        return []

    @field_validator("geo_regions", mode="before")
    @classmethod
    def sanitize_geo_regions(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [html.escape(str(r)[:100]) for r in v[:20]]
        return []


class ConsoleStoryUpdate(ConsoleStoryCreate):
    # Optimistic-lock guard. When provided, the save is rejected with 409 if the
    # story has been modified since the client loaded it (version moved on).
    expected_version: Optional[int] = None


class ConsoleStoryStatusUpdate(BaseModel):
    status: ConsoleStoryStatus
    scheduled_for: Optional[str] = None
    editor_note: Optional[str] = None
    expected_version: Optional[int] = None


class AuthorRead(BaseModel):
    id: str
    display_name: Optional[str]
    email: str
    role: str

    model_config = {"from_attributes": True}


class ConsoleStoryRead(BaseModel):
    id: str
    author: AuthorRead
    title: str
    standfirst: str
    sections: list[SectionData]
    cover_image: Optional[str]
    category: str
    tags: list[str]
    story_type: str
    status: ConsoleStoryStatus
    scheduled_for: Optional[str]
    word_count: int
    editor_note: Optional[str]
    geo_regions: list[str]
    is_featured: bool
    is_editorial_pick: bool
    issue_cluster_id: Optional[str]
    version: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ── Story comment (editorial thread) schemas ──────────────────────────────────

class StoryCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body", mode="before")
    @classmethod
    def sanitize_body(cls, v: object) -> str:
        # Comments are plain text — escape everything, no HTML.
        return html.escape(str(v).strip()[:5000]) if v else ""


class StoryCommentAuthorRead(BaseModel):
    id: str
    display_name: Optional[str]
    email: str
    role: str

    model_config = {"from_attributes": True}


class StoryCommentRead(BaseModel):
    id: str
    story_id: str
    author: StoryCommentAuthorRead
    body: str
    is_resolved: bool
    resolved_by_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class StoryCommentResolve(BaseModel):
    is_resolved: bool


# ── Issue cluster schemas ─────────────────────────────────────────────────────

class IssueClusterCreate(BaseModel):
    name: str = Field(max_length=200)
    slug: str = Field(default="", max_length=220)
    description: str = Field(default="")
    category: str = Field(default="", max_length=100)
    status: IssueClusterStatus = Field(default=IssueClusterStatus.active)
    breaking_order: Optional[int] = None
    breaking_expires_at: Optional[str] = None
    cover_image: Optional[str] = Field(default=None, max_length=500)
    assigned_editor_id: Optional[str] = None


class IssueClusterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=100)
    status: Optional[IssueClusterStatus] = None
    breaking_order: Optional[int] = None
    breaking_expires_at: Optional[str] = None
    cover_image: Optional[str] = Field(default=None, max_length=500)
    assigned_editor_id: Optional[str] = None


class AssignedEditorRead(BaseModel):
    id: str
    display_name: Optional[str]
    email: str

    model_config = {"from_attributes": True}


class IssueClusterRead(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    category: str
    status: str
    breaking_order: Optional[int]
    breaking_expires_at: Optional[str]
    cover_image: Optional[str]
    story_count: int
    created_by_id: str
    assigned_editor: Optional[AssignedEditorRead]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}
