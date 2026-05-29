from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.articles.models import Article
from app.articles.schemas import ArticleCard, FeedResponse
from app.console.models import IssueCluster, IssueClusterStatus
from app.ai.cache import cache_get, cache_set

router = APIRouter(prefix="/api/issues", tags=["issues"])

_PUBLIC_HEADERS = {"Cache-Control": "public, max-age=60, stale-while-revalidate=300"}


class PublicIssueRead(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    category: str
    status: str
    breaking_order: int | None
    breaking_expires_at: str | None
    cover_image: str | None
    article_count: int
    editor_name: str | None
    created_at: str
    updated_at: str


def _effective_status(cluster: IssueCluster) -> str:
    """Return effective status, downgrading breaking→active if expiry has passed."""
    if cluster.status == IssueClusterStatus.breaking and cluster.breaking_expires_at:
        if cluster.breaking_expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return IssueClusterStatus.active.value
    return cluster.status.value


async def _cluster_to_public(cluster: IssueCluster) -> PublicIssueRead:
    article_count = await Article.filter(issue_cluster_id=cluster.id).count()

    editor_name: str | None = None
    if cluster.assigned_editor_id:
        try:
            from app.auth.models import User
            editor = await User.get(id=cluster.assigned_editor_id)
            editor_name = editor.display_name or editor.email
        except Exception:
            pass

    return PublicIssueRead(
        id=str(cluster.id),
        name=cluster.name,
        slug=cluster.slug,
        description=cluster.description,
        category=cluster.category,
        status=_effective_status(cluster),
        breaking_order=cluster.breaking_order,
        breaking_expires_at=cluster.breaking_expires_at.isoformat() if cluster.breaking_expires_at else None,
        cover_image=cluster.cover_image,
        article_count=article_count,
        editor_name=editor_name,
        created_at=cluster.created_at.isoformat(),
        updated_at=cluster.updated_at.isoformat(),
    )


@router.get("")
async def list_public_issues():
    """List all active and breaking issue clusters, sorted breaking first."""
    cache_key = "pub:issues:list"
    if (cached := await cache_get(cache_key)) is not None:
        return JSONResponse(content=cached, headers=_PUBLIC_HEADERS)

    clusters = await IssueCluster.filter(
        status__in=[IssueClusterStatus.active, IssueClusterStatus.breaking]
    ).order_by("status", "-updated_at")

    data = [
        (await _cluster_to_public(c)).model_dump(mode="json")
        for c in sorted(
            clusters,
            key=lambda c: (0 if c.status == IssueClusterStatus.breaking else 1, -(c.breaking_order or 0)),
        )
    ]
    await cache_set(cache_key, data, ttl=60)
    return JSONResponse(content=data, headers=_PUBLIC_HEADERS)


@router.get("/{slug}")
async def get_public_issue(slug: str):
    """Get a single issue cluster by slug."""
    cache_key = f"pub:issue:{slug}"
    if (cached := await cache_get(cache_key)) is not None:
        return JSONResponse(content=cached, headers=_PUBLIC_HEADERS)

    cluster = await IssueCluster.filter(slug=slug).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Issue not found")

    data = (await _cluster_to_public(cluster)).model_dump(mode="json")
    await cache_set(cache_key, data, ttl=60)
    return JSONResponse(content=data, headers=_PUBLIC_HEADERS)


@router.get("/{slug}/articles")
async def get_issue_articles(
    slug: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    """Paginated list of published articles linked to this issue cluster."""
    cluster = await IssueCluster.filter(slug=slug).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Issue not found")

    cache_key = f"pub:issue:{slug}:articles:{page}:{limit}"
    if (cached := await cache_get(cache_key)) is not None:
        return JSONResponse(content=cached, headers=_PUBLIC_HEADERS)

    qs = Article.filter(issue_cluster_id=cluster.id)
    total = await qs.count()
    pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit
    articles = await qs.order_by("-published_at").limit(limit).offset(offset)

    cards = []
    for a in articles:
        card = ArticleCard.model_validate(a).model_dump(mode="json")
        card["issue_cluster_slug"] = cluster.slug
        card["issue_cluster_name"] = cluster.name
        cards.append(card)

    result = FeedResponse(
        articles=[ArticleCard.model_validate(a) for a in articles],
        total=total,
        page=page,
        pages=pages,
    ).model_dump(mode="json")
    result["articles"] = cards

    await cache_set(cache_key, result, ttl=60)
    return JSONResponse(content=result, headers=_PUBLIC_HEADERS)
