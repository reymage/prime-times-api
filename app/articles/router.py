from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from tortoise.expressions import Q

from app.articles.models import Article
from app.articles.schemas import ArticleCard, ArticleDetail, FeedResponse
from app.auth.dependencies import fastapi_users
from app.auth.models import User, UserPreferences
from app.ai.cache import cache_get, cache_set

router = APIRouter(prefix="/api", tags=["articles"])

_optional_user = fastapi_users.current_user(active=True, optional=True)

# Cache-Control for public, non-personalised responses
_PUBLIC_HEADERS = {"Cache-Control": "public, max-age=60, stale-while-revalidate=300"}
_ARTICLE_HEADERS = {"Cache-Control": "public, max-age=300, stale-while-revalidate=600"}


@router.get("/feed/hero")
async def get_hero(limit: int = Query(5, ge=1, le=10)):
    """Up to `limit` featured articles for the hero slider."""
    cache_key = f"feed:hero:{limit}"
    if (cached := await cache_get(cache_key)) is not None:
        return JSONResponse(content=cached, headers=_PUBLIC_HEADERS)

    featured = await Article.filter(is_featured=True).order_by("-published_at").limit(limit)
    if len(featured) < limit:
        ids = [a.id for a in featured]
        extra = await Article.exclude(id__in=ids).order_by("-published_at").limit(limit - len(featured))
        featured = list(featured) + list(extra)

    data = [ArticleCard.model_validate(a).model_dump(mode="json") for a in featured]
    await cache_set(cache_key, data, ttl=60)
    return JSONResponse(content=data, headers=_PUBLIC_HEADERS)


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
    personalized = False
    active_topics: list[str] = []

    if current_user:
        try:
            prefs, _ = await UserPreferences.get_or_create(user_id=current_user.id)
            active_topics = prefs.topics or []
            if not city:
                city = prefs.city or None
        except Exception:
            pass
    elif topics:
        active_topics = [t.strip() for t in topics.split(",") if t.strip()]

    is_public = current_user is None and not active_topics and not city
    cache_key = f"feed:{category or ''}:{page}:{limit}" if is_public else None

    if cache_key and (cached := await cache_get(cache_key)) is not None:
        return JSONResponse(content=cached, headers=_PUBLIC_HEADERS)

    qs = Article.all()
    if category:
        qs = qs.filter(category=category)
    if city:
        qs = qs.filter(tags__contains=city) | Article.all().filter(category__icontains=city)
        if category:
            qs = Article.all().filter(category=category)

    total = await qs.count()
    pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit

    if active_topics:
        personalized = True
        in_topic = (
            await qs.filter(category__in=active_topics)
            .order_by("-published_at")
            .limit(limit)
            .offset(offset)
        )
        if len(in_topic) < limit:
            in_ids = [a.id for a in in_topic]
            extra = await (
                qs.exclude(id__in=in_ids)
                .order_by("-published_at")
                .limit(limit - len(in_topic))
                .offset(max(0, offset - await qs.filter(category__in=active_topics).count()))
            )
            articles = list(in_topic) + list(extra)
        else:
            articles = list(in_topic)
    else:
        articles = await qs.order_by("-published_at").limit(limit).offset(offset)

    feed = FeedResponse(
        articles=[ArticleCard.model_validate(a) for a in articles],
        total=total,
        page=page,
        pages=pages,
        personalized=personalized,
    )
    data = feed.model_dump(mode="json")

    if cache_key:
        await cache_set(cache_key, data, ttl=60)

    headers = _PUBLIC_HEADERS if is_public else {}
    return JSONResponse(content=data, headers=headers)


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
    data = {
        "name": author_name,
        "avatar": avatar,
        "article_count": total,
        "articles": [ArticleCard.model_validate(a).model_dump(mode="json") for a in articles],
        "page": page,
        "pages": pages,
    }
    return JSONResponse(content=data, headers=_PUBLIC_HEADERS)
