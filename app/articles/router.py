import asyncio
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from tortoise.expressions import Q

from app.articles.models import Article, SavedArticle, ArticleView, ArticleFeedback
from app.articles.schemas import ArticleCard, ArticleDetail, FeedResponse, FeedbackIn, ViewIn
from app.auth.dependencies import fastapi_users, current_active_user
from app.auth.models import User, UserPreferences
from app.ai.cache import cache_get, cache_set

router = APIRouter(prefix="/api", tags=["articles"])

_optional_user = fastapi_users.current_user(active=True, optional=True)

# Cache-Control for public, non-personalised responses
_PUBLIC_HEADERS = {"Cache-Control": "public, max-age=60, stale-while-revalidate=300"}
_ARTICLE_HEADERS = {"Cache-Control": "public, max-age=300, stale-while-revalidate=600"}


def _cards(articles) -> list[dict]:
    return [ArticleCard.model_validate(a).model_dump(mode="json") for a in articles]


async def _resolve_topics(current_user: User | None, topics: str | None) -> list[str]:
    """Personalisation topics — from the logged-in user's prefs, else the query param."""
    if current_user:
        try:
            prefs, _ = await UserPreferences.get_or_create(user_id=current_user.id)
            return prefs.topics or []
        except Exception:
            return []
    if topics:
        return [t.strip() for t in topics.split(",") if t.strip()]
    return []


# ── Reusable section builders (each self-caches) ────────────────────────────
# Exposed as plain functions so the batched /feed/home endpoint can run them
# concurrently instead of forcing the client into one HTTP request per section.

async def _hero_data(limit: int = 5) -> list[dict]:
    cache_key = f"feed:hero:{limit}"
    if (cached := await cache_get(cache_key)) is not None:
        return cached
    featured = await Article.filter(is_featured=True).order_by("-published_at", "id").limit(limit)
    if len(featured) < limit:
        ids = [a.id for a in featured]
        extra = await Article.exclude(id__in=ids).order_by("-published_at", "id").limit(limit - len(featured))
        featured = list(featured) + list(extra)
    data = _cards(featured)
    await cache_set(cache_key, data, ttl=60)
    return data


async def _trending_data(limit: int = 6) -> list[dict]:
    cache_key = f"feed:trending:{limit}"
    if (cached := await cache_get(cache_key)) is not None:
        return cached
    articles = await Article.all().order_by("-view_count", "-published_at").limit(limit)
    data = _cards(articles)
    await cache_set(cache_key, data, ttl=120)
    return data


async def _editorial_data(limit: int = 6) -> list[dict]:
    cache_key = f"feed:editorial-picks:{limit}"
    if (cached := await cache_get(cache_key)) is not None:
        return cached
    picks = await Article.filter(is_editorial_pick=True).order_by("-published_at").limit(limit)
    data = _cards(picks)
    await cache_set(cache_key, data, ttl=60)
    return data


async def _compute_feed(
    *,
    page: int = 1,
    limit: int = 20,
    category: str | None = None,
    city: str | None = None,
    active_topics: list[str] | None = None,
    want_count: bool = True,
) -> dict:
    """Build a feed page. When `want_count` is False the expensive COUNT(*)
    round-trip is skipped (used by the homepage, which never needs exact totals)."""
    active_topics = active_topics or []
    qs = Article.all()
    if category:
        qs = qs.filter(category__iexact=category)
    if city:
        if category:
            # Already scoped to the category; narrow further to city-tagged articles.
            qs = qs.filter(tags__contains=[city])
        else:
            qs = qs.filter(Q(tags__contains=[city]) | Q(category__icontains=city))

    offset = (page - 1) * limit
    personalized = False
    total = await qs.count() if want_count else 0

    if active_topics:
        in_topic_qs = qs.filter(category__in=active_topics).order_by("-published_at", "id")
        articles = list(await in_topic_qs.limit(limit).offset(offset))
        if len(articles) < limit:
            # The in-topic total is only needed to offset into the remaining
            # pool when paging past the first page.
            in_topic_total = (await in_topic_qs.count()) if offset else 0
            extra_offset = max(0, offset - in_topic_total)
            extra = list(
                await qs.exclude(category__in=active_topics)
                .order_by("-published_at", "id")
                .limit(limit - len(articles))
                .offset(extra_offset)
            )
            articles = articles + extra
        if articles:
            personalized = True
        else:
            articles = list(await qs.order_by("-published_at", "id").limit(limit).offset(offset))
    else:
        articles = list(await qs.order_by("-published_at", "id").limit(limit).offset(offset))

    if not want_count:
        # Approximate paging info without the extra COUNT round-trip.
        total = offset + len(articles)
    pages = max(1, (total + limit - 1) // limit)

    return FeedResponse(
        articles=[ArticleCard.model_validate(a) for a in articles],
        total=total,
        page=page,
        pages=pages,
        personalized=personalized,
    ).model_dump(mode="json")


@router.get("/feed/hero")
async def get_hero(limit: int = Query(5, ge=1, le=10)):
    """Up to `limit` featured articles for the hero slider."""
    return JSONResponse(content=await _hero_data(limit), headers=_PUBLIC_HEADERS)


@router.get("/feed/home")
async def get_home(
    topics: str | None = Query(None),
    current_user: User | None = Depends(_optional_user),
):
    """Batched homepage payload — hero, main feed, trending, editorial picks
    and tracked issues in a single request. The underlying queries run
    concurrently, collapsing ~6 client round-trips (and the cross-region
    latency they each pay) into one."""
    # Imported lazily to avoid an articles<->issues import cycle at module load.
    from app.issues.router import list_public_issues_data

    active_topics = await _resolve_topics(current_user, topics)
    is_public = current_user is None and not active_topics

    async def _main_feed() -> dict:
        if is_public and (cached := await cache_get("feed:home:main")) is not None:
            return cached
        data = await _compute_feed(page=1, limit=36, active_topics=active_topics, want_count=False)
        if is_public:
            await cache_set("feed:home:main", data, ttl=60)
        return data

    hero, feed, trending, editorial_picks, issues = await asyncio.gather(
        _hero_data(5),
        _main_feed(),
        _trending_data(6),
        _editorial_data(6),
        list_public_issues_data(),
    )

    payload = {
        "hero": hero,
        "feed": feed,
        "trending": trending,
        "editorial_picks": editorial_picks,
        "issues": issues,
    }
    headers = _PUBLIC_HEADERS if is_public else {}
    return JSONResponse(content=payload, headers=headers)


@router.get("/feed")
async def get_feed(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    category: str | None = Query(None),
    topics: str | None = Query(None),
    city: str | None = Query(None),
    current_user: User | None = Depends(_optional_user),
):
    """Paginated feed — personalised when the user has saved topics."""
    active_topics = await _resolve_topics(current_user, topics)

    is_public = current_user is None and not active_topics and not city
    cache_key = f"feed:{category or ''}:{page}:{limit}" if is_public else None

    if cache_key and (cached := await cache_get(cache_key)) is not None:
        return JSONResponse(content=cached, headers=_PUBLIC_HEADERS)

    data = await _compute_feed(
        page=page,
        limit=limit,
        category=category,
        city=city,
        active_topics=active_topics,
        want_count=True,
    )

    if cache_key:
        await cache_set(cache_key, data, ttl=60)

    headers = _PUBLIC_HEADERS if is_public else {}
    return JSONResponse(content=data, headers=headers)


@router.get("/feed/trending")
async def get_trending(limit: int = Query(6, ge=1, le=20)):
    """Articles sorted by view_count — powers the Making Waves section."""
    return JSONResponse(content=await _trending_data(limit), headers=_PUBLIC_HEADERS)


@router.get("/feed/editorial-picks")
async def get_editorial_picks(limit: int = Query(6, ge=1, le=20)):
    """Articles marked as editorial picks by editors."""
    return JSONResponse(content=await _editorial_data(limit), headers=_PUBLIC_HEADERS)


def _resolve_device_id(explicit: str | None, request: Request) -> str:
    """A stable per-device id. Prefer the client-supplied id; otherwise derive
    one from IP + User-Agent so anonymous readers are still de-duplicated."""
    if explicit:
        return explicit[:64]
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    ua = request.headers.get("user-agent", "")
    return hashlib.sha256(f"{ip}|{ua}".encode()).hexdigest()[:32]


@router.post("/articles/{slug}/view")
async def record_article_view(slug: str, request: Request, body: ViewIn | None = None):
    """Record a read. Bumps the raw counter every time, but only increments the
    unique-reader counter the first time a given device views this article."""
    article = await Article.filter(slug=slug).only("id", "view_count", "unique_view_count").first()
    if not article:
        return {"ok": True}
    device_id = _resolve_device_id(body.device_id if body else None, request)
    article.view_count += 1
    _, created = await ArticleView.get_or_create(article_id=article.id, device_id=device_id)
    if created:
        article.unique_view_count += 1
        await article.save(update_fields=["view_count", "unique_view_count"])
    else:
        await article.save(update_fields=["view_count"])
    return {"ok": True, "unique_views": article.unique_view_count}


@router.post("/articles/{slug}/share")
async def record_article_share(slug: str):
    """Increment share_count. Fired from the frontend on a successful share
    (native share completed, link copied, or a share-platform window opened)."""
    article = await Article.filter(slug=slug).only("id", "share_count").first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    article.share_count += 1
    await article.save(update_fields=["share_count"])
    return {"shares": article.share_count}


@router.post("/articles/{slug}/feedback")
async def record_article_feedback(slug: str, request: Request, body: FeedbackIn):
    """Record reader feedback — 'Did this story help you understand the issue?'.
    One vote per device; a device may switch yes<->no but only counts once."""
    article = await Article.filter(slug=slug).only("id", "helpful_yes", "helpful_no").first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    device_id = _resolve_device_id(body.device_id, request)
    fb = await ArticleFeedback.get_or_none(article_id=article.id, device_id=device_id)

    if fb is None:
        await ArticleFeedback.create(article_id=article.id, device_id=device_id, helpful=body.helpful)
        if body.helpful:
            article.helpful_yes += 1
        else:
            article.helpful_no += 1
        await article.save(update_fields=["helpful_yes", "helpful_no"])
    elif fb.helpful != body.helpful:
        # Switch the vote — move the count from one bucket to the other.
        if body.helpful:
            article.helpful_yes += 1
            article.helpful_no = max(0, article.helpful_no - 1)
        else:
            article.helpful_no += 1
            article.helpful_yes = max(0, article.helpful_yes - 1)
        fb.helpful = body.helpful
        await fb.save(update_fields=["helpful", "updated_at"])
        await article.save(update_fields=["helpful_yes", "helpful_no"])
    # same vote repeated → no-op

    return {"helpful_yes": article.helpful_yes, "helpful_no": article.helpful_no}


@router.get("/articles/{slug}")
async def get_article(slug: str):
    cache_key = f"article:{slug}"
    if (cached := await cache_get(cache_key)) is not None:
        return JSONResponse(content=cached, headers=_ARTICLE_HEADERS)

    article = await Article.filter(slug=slug).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    related = (
        await Article.filter(category=article.category)
        .exclude(id=article.id)
        .order_by("-published_at")
        .limit(5)
    )

    detail = ArticleDetail.model_validate(article)
    detail.related = [ArticleCard.model_validate(r) for r in related]
    data = detail.model_dump(mode="json")
    await cache_set(cache_key, data, ttl=300)
    return JSONResponse(content=data, headers=_ARTICLE_HEADERS)


@router.get("/articles/{slug}/next")
async def get_next_article(
    slug: str,
    topics: str | None = Query(None),
    exclude: str | None = Query(None),
    current_user: User | None = Depends(_optional_user),
):
    """Next article for seamless reading. Respects personalisation."""
    current = await Article.filter(slug=slug).first()
    if not current:
        raise HTTPException(status_code=404, detail="Article not found")

    exclude_slugs = [s.strip() for s in (exclude or "").split(",") if s.strip()]
    exclude_slugs.append(slug)

    active_topics: list[str] = []
    if current_user:
        try:
            prefs, _ = await UserPreferences.get_or_create(user_id=current_user.id)
            active_topics = prefs.topics or []
        except Exception:
            pass
    elif topics:
        active_topics = [t.strip() for t in topics.split(",") if t.strip()]

    is_public = current_user is None and not active_topics
    cache_key = f"next:{slug}:{','.join(sorted(exclude_slugs))}" if is_public else None

    if cache_key and (cached := await cache_get(cache_key)) is not None:
        return JSONResponse(content=cached, headers=_PUBLIC_HEADERS)

    qs = Article.exclude(slug__in=exclude_slugs).order_by("-published_at")

    next_article = None
    if active_topics:
        if current.category in active_topics:
            next_article = await qs.filter(category=current.category).first()
        if not next_article:
            next_article = await qs.filter(category__in=active_topics).first()

    if not next_article:
        next_article = await qs.filter(category=current.category).first()
    if not next_article:
        next_article = await qs.first()

    if not next_article:
        raise HTTPException(status_code=404, detail="No next article available")

    related = (
        await Article.filter(category=next_article.category)
        .exclude(id=next_article.id)
        .order_by("-published_at")
        .limit(5)
    )

    detail = ArticleDetail.model_validate(next_article)
    detail.related = [ArticleCard.model_validate(r) for r in related]
    data = detail.model_dump(mode="json")

    if cache_key:
        await cache_set(cache_key, data, ttl=120)

    headers = _PUBLIC_HEADERS if is_public else {}
    return JSONResponse(content=data, headers=headers)


@router.get("/search")
async def search_articles(
    q: str = Query(..., min_length=2),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    """Full-text search across article titles and excerpts."""
    q = q.strip()
    qs = Article.filter(Q(title__icontains=q) | Q(excerpt__icontains=q))
    total = await qs.count()
    pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit
    articles = await qs.order_by("-published_at").limit(limit).offset(offset)
    data = {
        "articles": [ArticleCard.model_validate(a).model_dump(mode="json") for a in articles],
        "total": total,
        "page": page,
        "pages": pages,
    }
    return JSONResponse(content=data, headers=_PUBLIC_HEADERS)


@router.post("/articles/{slug}/save", tags=["saved"])
async def save_article_endpoint(slug: str, current_user: User = Depends(current_active_user)):
    article = await Article.get_or_none(slug=slug)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    await SavedArticle.get_or_create(user_id=current_user.id, article_id=article.id)
    return {"saved": True}


@router.delete("/articles/{slug}/save", tags=["saved"])
async def unsave_article_endpoint(slug: str, current_user: User = Depends(current_active_user)):
    article = await Article.get_or_none(slug=slug)
    if article:
        await SavedArticle.filter(user_id=current_user.id, article_id=article.id).delete()
    return {"saved": False}


@router.get("/articles/{slug}/save-status", tags=["saved"])
async def get_save_status_endpoint(slug: str, current_user: User = Depends(current_active_user)):
    article = await Article.get_or_none(slug=slug)
    if not article:
        return {"saved": False}
    saved = await SavedArticle.filter(user_id=current_user.id, article_id=article.id).exists()
    return {"saved": saved}


@router.get("/users/me/saved", tags=["saved"])
async def get_my_saved_articles(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(current_active_user),
):
    total = await SavedArticle.filter(user_id=current_user.id).count()
    pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit
    saves = (
        await SavedArticle.filter(user_id=current_user.id)
        .prefetch_related("article")
        .order_by("-saved_at")
        .offset(offset)
        .limit(limit)
    )
    articles = [ArticleCard.model_validate(s.article).model_dump(mode="json") for s in saves]
    return {"articles": articles, "total": total, "page": page, "pages": pages}


@router.get("/authors/{author_name}")
async def get_author_profile(
    author_name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50),
):
    """Public author profile — returns their info and recent articles."""
    qs = Article.filter(author=author_name)
    total = await qs.count()
    if total == 0:
        raise HTTPException(status_code=404, detail="Author not found")
    pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit
    articles = await qs.order_by("-published_at").limit(limit).offset(offset)
    avatar = next((a.author_avatar for a in articles if a.author_avatar), None)

    # Try to look up the user record for richer profile data (case-insensitive)
    user = await User.get_or_none(display_name=author_name)
    if not user:
        candidates = await User.filter(display_name__iexact=author_name).limit(1)
        user = candidates[0] if candidates else None

    data = {
        "name": author_name,
        "avatar": (user.avatar_url if user and user.avatar_url else None) or avatar,
        "bio": user.bio if user else None,
        "linkedin_url": user.linkedin_url if user else None,
        "twitter_url": user.twitter_url if user else None,
        "public_email": user.public_email if user else None,
        "article_count": total,
        "articles": [ArticleCard.model_validate(a).model_dump(mode="json") for a in articles],
        "page": page,
        "pages": pages,
    }
    return JSONResponse(content=data, headers=_PUBLIC_HEADERS)
