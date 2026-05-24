"""
AI endpoints:
  POST /ai/suggest   — desk → researcher → qc  (<4s)
  POST /ai/generate  — full graph              (<15s)
  GET  /ai/usage     — cost & usage analytics
"""
import asyncio
import logging
import time
from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.ai.agent.graph import generate_graph, suggest_graph
from app.ai.agent.state import initial_state
from app.ai.llm import TAVILY_COST_PER_SEARCH, estimate_llm_cost
from app.ai.models import AILog
from app.ai.schemas import (
    GenerateRequest,
    GenerateResponse,
    SourceRef,
    SuggestRequest,
    SuggestResponse,
    UsageRecord,
    UsageResponse,
)
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])

# ── Per-reporter rate limiter ─────────────────────────────────────────────────

class _ReporterRateLimiter:
    """Sliding-window rate limiter keyed by reporter_id."""

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, reporter_id: str) -> None:
        limit = settings.AI_RATE_LIMIT
        window = settings.AI_RATE_LIMIT_WINDOW
        now = time.monotonic()
        cutoff = now - window

        async with self._lock:
            timestamps = [t for t in self._windows[reporter_id] if t > cutoff]
            if len(timestamps) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: {limit} requests per {window}s per reporter.",
                )
            timestamps.append(now)
            self._windows[reporter_id] = timestamps


_rate_limiter = _ReporterRateLimiter()


# ── Source deduplication helper ───────────────────────────────────────────────

def _dedupe_sources(sources: list[dict]) -> list[SourceRef]:
    seen: set[str] = set()
    out: list[SourceRef] = []
    for s in sources:
        url = s.get("url", "")
        if url and url not in seen:
            seen.add(url)
            out.append(SourceRef(title=s.get("title", url), url=url))
    return out[:20]


# ── Cost logger ───────────────────────────────────────────────────────────────

async def _log_usage(
    reporter_id: str,
    endpoint: str,
    state: dict,
    duration_ms: int,
    cache_hit: bool,
    success: bool,
    error_code: str | None,
) -> None:
    in_t = state.get("total_input_tokens", 0)
    out_t = state.get("total_output_tokens", 0)
    searches = state.get("tavily_searches", 0)
    llm_cost = estimate_llm_cost(in_t, out_t)
    tavily_cost = searches * TAVILY_COST_PER_SEARCH

    try:
        await AILog.create(
            reporter_id=reporter_id,
            endpoint=endpoint,
            story_type=state.get("story_type"),
            llm_provider=settings.LLM_PROVIDER,
            llm_model=settings.GROQ_MODEL
            if settings.LLM_PROVIDER == "groq"
            else settings.OPENAI_MODEL,
            llm_input_tokens=in_t,
            llm_output_tokens=out_t,
            llm_cost_usd=Decimal(str(round(llm_cost, 8))),
            tavily_searches=searches,
            tavily_cost_usd=Decimal(str(round(tavily_cost, 8))),
            cache_hit=cache_hit,
            attempts=state.get("attempts", 0),
            rewrites=state.get("rewrites", 0),
            score=state.get("score") or None,
            success=success,
            error_code=error_code,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.error("Failed to write ai_log: %s", exc)


# ── POST /ai/suggest ──────────────────────────────────────────────────────────

@router.post("/suggest", response_model=SuggestResponse)
async def suggest(request: Request, body: SuggestRequest) -> SuggestResponse:
    await _rate_limiter.check(body.reporter_id)

    t0 = time.monotonic()
    state = initial_state(title=body.title, body=body.body)
    result: dict = {}
    success = True
    error_code: str | None = None

    try:
        result = await suggest_graph.ainvoke(state)
    except Exception as exc:
        logger.exception("suggest graph error: %s", exc)
        success = False
        error_code = "graph_error"
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable.")
    finally:
        duration_ms = int((time.monotonic() - t0) * 1000)
        log_state = result if result else state
        asyncio.create_task(
            _log_usage(
                reporter_id=body.reporter_id,
                endpoint="suggest",
                state=log_state,
                duration_ms=duration_ms,
                cache_hit=bool(log_state.get("cache_hits", 0) > 0),
                success=success,
                error_code=error_code,
            )
        )

    sources = _dedupe_sources(result.get("sources") or [])

    return SuggestResponse(
        angles=result.get("angles") or [],
        gaps=result.get("gaps") or [],
        sources=sources,
        confidence=result.get("confidence", 0),
    )


# ── POST /ai/generate ─────────────────────────────────────────────────────────

@router.post("/generate", response_model=GenerateResponse)
async def generate(request: Request, body: GenerateRequest) -> GenerateResponse:
    await _rate_limiter.check(body.reporter_id)

    t0 = time.monotonic()
    state = initial_state(
        title=body.title,
        body=body.body,
        highlighted_text=body.highlighted_text,
    )
    success = True
    error_code: str | None = None
    result: dict = {}

    try:
        result = await generate_graph.ainvoke(state)
    except Exception as exc:
        logger.exception("generate graph error: %s", exc)
        success = False
        error_code = "graph_error"
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable.")
    finally:
        duration_ms = int((time.monotonic() - t0) * 1000)
        asyncio.create_task(
            _log_usage(
                reporter_id=body.reporter_id,
                endpoint="generate",
                state=result if result else state,
                duration_ms=duration_ms,
                cache_hit=bool((result or {}).get("cache_hits", 0) > 0),
                success=success,
                error_code=error_code,
            )
        )

    if result.get("error") == "insufficient_research":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "insufficient_research",
                "message": "Insufficient research after maximum attempts.",
                "gaps": result.get("gaps", []),
                "warnings": result.get("warnings", []),
            },
        )

    sources = _dedupe_sources(result.get("sources") or [])

    return GenerateResponse(
        draft=result.get("draft", ""),
        sources=sources,
        attempts=result.get("attempts", 0),
        score=result.get("score", 0),
        warnings=result.get("warnings") or [],
    )


# ── GET /ai/usage ─────────────────────────────────────────────────────────────

@router.get("/usage", response_model=UsageResponse)
async def usage(
    reporter_id: str | None = None,
    endpoint: str | None = None,
    limit: int = 100,
) -> UsageResponse:
    limit = min(limit, 500)

    qs = AILog.all().order_by("-created_at")
    if reporter_id:
        qs = qs.filter(reporter_id=reporter_id)
    if endpoint:
        qs = qs.filter(endpoint=endpoint)

    logs: list[AILog] = await qs.limit(limit)

    total_llm = sum(float(r.llm_cost_usd) for r in logs)
    total_tavily = sum(float(r.tavily_cost_usd) for r in logs)

    records = [
        UsageRecord(
            id=str(r.id),
            reporter_id=r.reporter_id,
            endpoint=r.endpoint,
            story_type=r.story_type,
            llm_cost_usd=float(r.llm_cost_usd),
            tavily_cost_usd=float(r.tavily_cost_usd),
            cache_hit=r.cache_hit,
            attempts=r.attempts,
            score=r.score,
            success=r.success,
            duration_ms=r.duration_ms,
            created_at=r.created_at.isoformat(),
        )
        for r in logs
    ]

    return UsageResponse(
        records=records,
        total_llm_cost_usd=round(total_llm, 6),
        total_tavily_cost_usd=round(total_tavily, 6),
        total_requests=len(records),
    )
