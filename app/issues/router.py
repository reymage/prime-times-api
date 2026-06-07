from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from tortoise.functions import Count

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


def _cluster_to_public(
    cluster: IssueCluster,
    article_count: int,
    editor_name: str | None,
) -> PublicIssueRead:
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


async def _serialize_clusters(clusters: list[IssueCluster]) -> list[dict]:
    """Serialize clusters to public dicts, batching the per-cluster lookups.

    Replaces the old 2N+1 pattern (one COUNT + one User.get per cluster) with
    three queries total: clusters, a grouped article-count, and a batched
    editor lookup.
    """
    if not clusters:
        return []

    ids = [c.id for c in clusters]

    # One grouped query for all article counts instead of one COUNT per cluster.
    count_rows = (
        await Article.filter(issue_cluster_id__in=ids)
        .annotate(c=Count("id"))
        .group_by("issue_cluster_id")
        .values("issue_cluster_id", "c")
    )
    counts = {row["issue_cluster_id"]: row["c"] for row in count_rows}

    # One batched query for all assigned editors instead of one User.get each.
    editor_ids = {c.assigned_editor_id for c in clusters if c.assigned_editor_id}
    editors: dict = {}
    if editor_ids:
        from app.auth.models import User

        for u in await User.filter(id__in=list(editor_ids)).values(
            "id", "display_name", "email"
        ):
            editors[u["id"]] = u["display_name"] or u["email"]

    return [
        _cluster_to_public(
            c,
            article_count=counts.get(c.id, 0),
            editor_name=editors.get(c.assigned_editor_id),
        ).model_dump(mode="json")
        for c in clusters
    ]


async def list_public_issues_data() -> list[dict]:
    """Cached list of active/breaking issue clusters (breaking first).

    Exposed as a function so the batched home feed can reuse it without an
    extra HTTP round-trip.
    """
    cache_key = "pub:issues:list"
    if (cached := await cache_get(cache_key)) is not None:
        return cached

    clusters = await IssueCluster.filter(
        status__in=[IssueClusterStatus.active, IssueClusterStatus.breaking]
    ).order_by("status", "-updated_at")

    ordered = sorted(
        clusters,
        key=lambda c: (0 if c.status == IssueClusterStatus.breaking else 1, -(c.breaking_order or 0)),
    )
    data = await _serialize_clusters(ordered)
    await cache_set(cache_key, data, ttl=60)
    return data


@router.get("")
async def list_public_issues():
    """List all active and breaking issue clusters, sorted breaking first."""
    data = await list_public_issues_data()
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

    serialized = await _serialize_clusters([cluster])
    data = serialized[0]
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
    articles = await qs.order_by("-published_at", "id").limit(limit).offset(offset)

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
