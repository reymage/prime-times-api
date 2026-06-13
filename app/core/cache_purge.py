"""Cloudflare edge-cache purge — keeps the public site fresh on publish.

The frontend serves public pages (home, article, category, …) with a short
edge-cache TTL (`s-maxage` + `stale-while-revalidate`). That makes the site fast
and cheap, but means a freshly published or edited story can lag behind by up to
the TTL. Calling :func:`purge_article` the moment a story is synced bursts the
relevant URLs from Cloudflare's edge so breaking news shows up immediately.

Everything here is fail-safe: a purge error is logged but never raised, so it can
never break publishing. If Cloudflare credentials aren't configured, it no-ops.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_CF_PURGE_URL = "https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache"


def _slugify_category(category: str | None) -> str:
    """Match the frontend's `/category/<slug>` URL form (lowercase, hyphenated)."""
    return re.sub(r"[^a-z0-9]+", "-", (category or "").lower()).strip("-")


async def purge_paths(paths: list[str]) -> None:
    """Purge the given site paths from Cloudflare's edge cache.

    No-op when CLOUDFLARE_ZONE_ID / CLOUDFLARE_API_TOKEN are unset. Never raises.
    """
    from app.config import settings

    if not (settings.CLOUDFLARE_ZONE_ID and settings.CLOUDFLARE_API_TOKEN):
        logger.debug("Cloudflare purge skipped — credentials not configured")
        return

    base = (settings.PUBLIC_SITE_URL or settings.FRONTEND_URL).rstrip("/")
    # De-dupe while preserving order; build absolute URLs Cloudflare expects.
    files = [
        f"{base}{p if p.startswith('/') else '/' + p}"
        for p in dict.fromkeys(paths)
    ]
    if not files:
        return

    url = _CF_PURGE_URL.format(zone=settings.CLOUDFLARE_ZONE_ID)
    headers = {
        "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json={"files": files})
        if resp.status_code == 200 and resp.json().get("success"):
            logger.info("Purged %d URL(s) from Cloudflare edge cache", len(files))
        else:
            logger.warning(
                "Cloudflare purge failed (%s): %s", resp.status_code, resp.text[:300]
            )
    except Exception as exc:  # noqa: BLE001 — purging must never break publishing
        logger.warning("Cloudflare purge error: %s", exc)


async def purge_article(slug: str, category: str | None = None) -> None:
    """Purge the public surfaces a published/updated article appears on.

    Covers the home feed, the article's own page, and its category section.
    """
    paths = ["/", f"/news/{slug}"]
    cat = _slugify_category(category)
    if cat:
        paths.append(f"/category/{cat}")
    await purge_paths(paths)
