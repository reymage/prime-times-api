from fastapi import APIRouter, Depends, HTTPException, Query

from app.articles.models import Article
from app.articles.schemas import ArticleCard, ArticleDetail, FeedResponse
from app.auth.dependencies import fastapi_users
from app.auth.models import User, UserPreferences

router = APIRouter(prefix="/api", tags=["articles"])

# Optional auth — never raises 401 when no token is present
_optional_user = fastapi_users.current_user(active=True, optional=True)


@router.get("/feed/hero", response_model=list[ArticleCard])
async def get_hero(limit: int = Query(5, ge=1, le=10)) -> list[Article]:
    """Up to `limit` featured articles for the hero slider."""
    featured = await Article.filter(is_featured=True).order_by("-published_at").limit(limit)
    if len(featured) < limit:
        ids = [a.id for a in featured]
        extra = await (
            Article.exclude(id__in=ids).order_by("-published_at").limit(limit - len(featured))
        )
        featured = list(featured) + list(extra)
    return featured


@router.get("/feed", response_model=FeedResponse)
async def get_feed(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    category: str | None = Query(None),
    # Guest personalisation — comma-separated topics (also used by mobile app)
    topics: str | None = Query(None),
    city: str | None = Query(None),
    current_user: User | None = Depends(_optional_user),
) -> FeedResponse:
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
        # Guest/mobile: topics passed explicitly
        active_topics = [t.strip() for t in topics.split(",") if t.strip()]

    qs = Article.all()
    if category:
        qs = qs.filter(category=category)
    if city:
        # Filter city-tagged articles when city is set (articles with matching tag or category)
        qs = qs.filter(tags__contains=city) | Article.all().filter(category__icontains=city)
        # Re-apply category filter if needed
        if category:
            qs = Article.all().filter(category=category)

    total = await qs.count()
    pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit

    if active_topics:
        personalized = True
        in_topic = await qs.filter(category__in=active_topics).order_by("-published_at").limit(limit).offset(offset)
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

    return FeedResponse(
        articles=[ArticleCard.model_validate(a) for a in articles],
        total=total,
        page=page,
        pages=pages,
        personalized=personalized,
    )


@router.get("/articles/{slug}", response_model=ArticleDetail)
async def get_article(slug: str) -> ArticleDetail:
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
    return detail


@router.get("/articles/{slug}/next", response_model=ArticleDetail)
async def get_next_article(
    slug: str,
    topics: str | None = Query(None),
    exclude: str | None = Query(None),
    current_user: User | None = Depends(_optional_user),
) -> ArticleDetail:
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

    qs = Article.exclude(slug__in=exclude_slugs).order_by("-published_at")

    # Prefer same category, then personalised topics, then latest
    next_article = None
    if active_topics:
        # Try same category first if in topics
        if current.category in active_topics:
            next_article = await qs.filter(category=current.category).first()
        # Then any topic article
        if not next_article:
            next_article = await qs.filter(category__in=active_topics).first()

    if not next_article:
        # Fallback: same category
        next_article = await qs.filter(category=current.category).first()
    if not next_article:
        # Final fallback: any latest article
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
    return detail
