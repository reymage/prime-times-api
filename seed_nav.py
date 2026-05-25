"""
Reset and reseed the main navigation menu.
Run from the api/ directory:
    python seed_nav.py

Safe to run multiple times — it deactivates stale items then upserts the list below.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


NAV_ITEMS = [
    # ── News mega-menu trigger (must have slug="news") ────────────────────────
    {"label": "News",           "slug": "news",           "href": "/",                        "item_type": "primary",  "position": 0},
    # ── Direct nav links (left → right order, shown after the News dropdown) ──
    {"label": "Politics",       "slug": "politics",       "href": "/category/politics",       "item_type": "primary",  "position": 1},
    {"label": "Market",         "slug": "market",         "href": "/category/economy",        "item_type": "primary",  "position": 2},
    {"label": "Technology",     "slug": "technology",     "href": "/category/technology",     "item_type": "primary",  "position": 3},
    {"label": "Entertainment",  "slug": "entertainment",  "href": "/category/entertainment",  "item_type": "primary",  "position": 4},
    {"label": "International",  "slug": "international",  "href": "/category/international",  "item_type": "primary",  "position": 5},
    # ── Breaking / hot topics (shown with red pulse dot) ─────────────────────
    {"label": "Iran Tension",   "slug": "iran-tension",   "href": "/category/iran-tension",   "item_type": "breaking", "position": 1},
    {"label": "2027 Election",  "slug": "2027-election",  "href": "/category/2027-election",  "item_type": "breaking", "position": 2},
    # ── Mega-menu category grid (shown inside the News dropdown) ─────────────
    {"label": "Politics",       "slug": "cat-politics",       "href": "/category/politics",       "item_type": "category", "position": 1},
    {"label": "Economy",        "slug": "cat-economy",        "href": "/category/economy",        "item_type": "category", "position": 2},
    {"label": "Business",       "slug": "cat-business",       "href": "/category/business",       "item_type": "category", "position": 3},
    {"label": "Technology",     "slug": "cat-technology",     "href": "/category/technology",     "item_type": "category", "position": 4},
    {"label": "Entertainment",  "slug": "cat-entertainment",  "href": "/category/entertainment",  "item_type": "category", "position": 5},
    {"label": "International",  "slug": "cat-international",  "href": "/category/international",  "item_type": "category", "position": 6},
    {"label": "Issues",         "slug": "cat-issues",         "href": "/category/issues",         "item_type": "category", "position": 7},
    {"label": "Energy",         "slug": "cat-energy",         "href": "/category/energy",         "item_type": "category", "position": 8},
]


async def main() -> None:
    from tortoise import Tortoise
    from app.config import settings
    from app.nav.models import NavMenu

    await Tortoise.init(
        db_url=settings.DATABASE_URL,
        modules={
            "models": [
                "app.auth.models",
                "app.console.models",
                "app.nav.models",
                "app.ai.models",
            ]
        },
    )

    # Deactivate all existing main-area nav items so stale ones disappear.
    deactivated = await NavMenu.filter(area="main").update(is_active=False)
    print(f"Deactivated {deactivated} existing main nav items")

    created = updated = 0
    for item in NAV_ITEMS:
        existing = await NavMenu.filter(slug=item["slug"]).first()
        if existing:
            for k, v in item.items():
                setattr(existing, k, v)
            existing.is_active = True
            existing.area = "main"
            await existing.save()
            updated += 1
        else:
            await NavMenu.create(**item, area="main", is_active=True)
            created += 1

    print(f"Nav menu seeded: {created} created, {updated} updated ({len(NAV_ITEMS)} total)")
    await Tortoise.close_connections()


asyncio.run(main())
