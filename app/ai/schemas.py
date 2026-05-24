from pydantic import BaseModel, Field, field_validator


# ── Input sanitisation ────────────────────────────────────────────────────────

import html
import re

_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions",
    r"forget\s+(?:everything|all\s+previous)",
    r"you\s+are\s+now\s+(?:a|an)",
    r"new\s+(?:instructions|task|persona|role|system)",
    r"<\s*\/?(?:system|human|assistant|user)\s*>",
    r"\[INST\]|\[/INST\]|<\|im_start\|>|<\|im_end\|>",
    r"###\s*(?:System|Instruction|Human|Assistant)\s*:",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def _sanitize(text: str, max_length: int = 8000) -> str:
    text = text[:max_length]
    text = html.escape(text)
    text = _INJECTION_RE.sub("[REMOVED]", text)
    return text.strip()


# ── Request schemas ───────────────────────────────────────────────────────────

class SuggestRequest(BaseModel):
    title: str = Field(..., min_length=5, max_length=300)
    body: str = Field(..., min_length=50, max_length=8000)
    reporter_id: str = Field(..., min_length=1, max_length=255)

    @field_validator("title", "body", "reporter_id", mode="before")
    @classmethod
    def sanitize_fields(cls, v: str) -> str:
        return _sanitize(str(v))


class GenerateRequest(BaseModel):
    title: str = Field(..., min_length=5, max_length=300)
    body: str = Field(..., min_length=50, max_length=8000)
    highlighted_text: str | None = Field(default=None, max_length=2000)
    reporter_id: str = Field(..., min_length=1, max_length=255)

    @field_validator("title", "body", "reporter_id", mode="before")
    @classmethod
    def sanitize_fields(cls, v: str) -> str:
        return _sanitize(str(v))

    @field_validator("highlighted_text", mode="before")
    @classmethod
    def sanitize_highlight(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = _sanitize(str(v), max_length=2000)
        return cleaned if cleaned else None


# ── Response schemas ──────────────────────────────────────────────────────────

class SourceRef(BaseModel):
    title: str
    url: str


class SuggestResponse(BaseModel):
    angles: list[str]
    gaps: list[str]
    sources: list[SourceRef]
    confidence: int


class GenerateResponse(BaseModel):
    draft: str
    sources: list[SourceRef]
    attempts: int
    score: int
    warnings: list[str]


class UsageRecord(BaseModel):
    id: str
    reporter_id: str
    endpoint: str
    story_type: str | None
    llm_cost_usd: float
    tavily_cost_usd: float
    cache_hit: bool
    attempts: int
    score: int | None
    success: bool
    duration_ms: int
    created_at: str


class UsageResponse(BaseModel):
    records: list[UsageRecord]
    total_llm_cost_usd: float
    total_tavily_cost_usd: float
    total_requests: int
