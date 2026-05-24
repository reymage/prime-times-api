"""
Caching layer for LLM calls and Tavily searches.
Uses Redis when REDIS_URL is set, falls back to in-memory LRU.
"""
import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# ── In-memory LRU ──────────────────────────────────────────────────────────────

class _LRUCache:
    """Thread-safe async-compatible in-memory LRU with TTL."""

    def __init__(self, max_size: int = 512):
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            if key not in self._store:
                return None
            value, expires_at = self._store[key]
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        async with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, time.monotonic() + ttl)
            if len(self._store) > self._max_size:
                self._store.popitem(last=False)


_lru: _LRUCache = _LRUCache()

# ── Redis client (lazy init) ───────────────────────────────────────────────────

_redis_client: Any = None
_redis_lock = asyncio.Lock()


async def _get_redis() -> Any | None:
    global _redis_client
    if not settings.REDIS_URL:
        return None
    async with _redis_lock:
        if _redis_client is None:
            try:
                import redis.asyncio as aioredis

                _redis_client = await aioredis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
                await _redis_client.ping()
                logger.info("Redis cache connected: %s", settings.REDIS_URL)
            except Exception as exc:
                logger.warning("Redis unavailable (%s), using in-memory LRU", exc)
                _redis_client = None
    return _redis_client


# ── Cache primitives ───────────────────────────────────────────────────────────

async def cache_get(key: str) -> Any | None:
    r = await _get_redis()
    if r:
        try:
            raw = await r.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.debug("Redis get failed: %s", exc)
    return await _lru.get(key)


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    ttl = ttl if ttl is not None else settings.CACHE_TTL_SECONDS
    r = await _get_redis()
    if r:
        try:
            await r.setex(key, ttl, json.dumps(value, default=str))
            return
        except Exception as exc:
            logger.debug("Redis set failed: %s", exc)
    await _lru.set(key, value, ttl)


# ── Key builders ───────────────────────────────────────────────────────────────

def _llm_cache_key(model_name: str, messages: list[dict], temperature: float) -> str:
    payload = json.dumps(
        {"model": model_name, "messages": messages, "temp": temperature},
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"llm:{digest}"


def _tavily_cache_key(query: str, search_depth: str) -> str:
    payload = json.dumps({"q": query, "depth": search_depth}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"tavily:{digest}"


def _precedent_cache_key(key_entities: list[str], story_type: str) -> str:
    payload = json.dumps({"entities": sorted(key_entities), "type": story_type}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"prec:{digest}"


# ── Public decorators / helpers ────────────────────────────────────────────────

async def cached_llm_invoke(
    llm: Any,
    messages: list,
    temperature: float,
) -> tuple[Any, bool]:
    """
    Invoke an LLM with caching.
    Returns (AIMessage, cache_hit: bool).
    """
    # Serialize messages to a stable dict representation
    msg_dicts = [{"role": m.type, "content": m.content} for m in messages]
    model_name = getattr(llm, "model_name", None) or getattr(llm, "model", "unknown")
    key = _llm_cache_key(model_name, msg_dicts, temperature)

    cached = await cache_get(key)
    if cached is not None:
        from langchain_core.messages import AIMessage

        return AIMessage(content=cached["content"]), True

    response = await llm.ainvoke(messages)
    await cache_set(key, {"content": response.content})
    return response, False


async def cached_tavily_search(
    query: str,
    search_depth: str = "advanced",
) -> tuple[dict, bool]:
    """
    Run a Tavily search with caching.
    Returns (result_dict, cache_hit: bool).
    """
    key = _tavily_cache_key(query, search_depth)

    cached = await cache_get(key)
    if cached is not None:
        return cached, True

    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=settings.TAVILY_API_KEY)
    result = await client.search(query, search_depth=search_depth, max_results=15)
    await cache_set(key, result)
    return result, False
