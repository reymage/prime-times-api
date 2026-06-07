"""
Console story endpoints — editorial workflow for writers and editors.

Role visibility:
  reporter / contributor  → own stories only
  editor / admin / super_admin → all stories
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.auth.dependencies import current_active_user
from app.auth.models import User
from app.articles.models import Article
from app.console.models import ConsoleStory, ConsoleStoryStatus, IssueCluster, IssueClusterStatus
from app.nav.models import NavArea, NavItemType, NavMenu
from app.console.schemas import (
    AssignedEditorRead,
    AuthorRead,
    ConsoleStoryCreate,
    ConsoleStoryRead,
    ConsoleStoryStatusUpdate,
    ConsoleStoryUpdate,
    IssueClusterCreate,
    IssueClusterRead,
    IssueClusterUpdate,
    SectionData,
)
from app.core.roles import UserRole, role_has_at_least
from app.notifications.models import NotificationType
from app.notifications.service import create_notification

logger = logging.getLogger(__name__)


async def _notify_story(
    story: "ConsoleStory",
    notif_type: NotificationType,
    title: str,
    body: str,
    sender_id: uuid.UUID | None = None,
) -> None:
    """Fire a notification to the story author; swallow all errors."""
    try:
        author_id = story.author_id
        if author_id and str(author_id) != str(sender_id):
            await create_notification(
                recipient_id=author_id,
                notif_type=notif_type,
                title=title,
                body=body,
                link=f"/console/editor/{story.id}",
                sender_id=sender_id,
            )
    except Exception as exc:
        logger.warning("notification failed for story %s: %s", story.id, exc)


async def _notify_editorial_team(
    story: "ConsoleStory",
    notif_type: NotificationType,
    title: str,
    body: str,
    sender_id: uuid.UUID | None = None,
) -> None:
    """Notify all active editors/admins about a story event; swallow all errors."""
    try:
        from app.auth.models import User
        editors = await User.filter(is_active=True).values_list("id", "role")
        editorial_roles = {"editor", "admin", "super_admin"}
        for editor_id, role in editors:
            if role in editorial_roles and str(editor_id) != str(sender_id):
                await create_notification(
                    recipient_id=editor_id,
                    notif_type=notif_type,
                    title=title,
                    body=body,
                    link="/console/reviews",
                    sender_id=sender_id,
                )
    except Exception as exc:
        logger.warning("editorial notification failed for story %s: %s", story.id, exc)


# ── Publish pipeline helpers ──────────────────────────────────────────────────

def _slugify(text: str, suffix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]
    return f"{slug}-{suffix}" if slug else f"story-{suffix}"


def _sections_to_html(sections: list) -> str:
    parts = []
    for s in sections:
        stype = s.get("type", "text")
        if stype == "text":
            if s.get("heading"):
                parts.append(f'<h2>{s["heading"]}</h2>')
            if s.get("content"):
                parts.append(s["content"])
        elif stype == "image" and s.get("src"):
            alt = s.get("alt", "")
            cap = s.get("caption", "")
            parts.append(
                f'<figure><img src="{s["src"]}" alt="{alt}" style="max-width:100%"/>'
                + (f"<figcaption>{cap}</figcaption>" if cap else "")
                + "</figure>"
            )
        elif stype == "video" and s.get("video_id"):
            vid = s["video_id"]
            if s.get("provider", "youtube") == "youtube":
                parts.append(
                    f'<figure style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden">'
                    f'<iframe src="https://www.youtube-nocookie.com/embed/{vid}" '
                    f'style="position:absolute;top:0;left:0;width:100%;height:100%;border:0" allowfullscreen></iframe>'
                    f"</figure>"
                )
    return "".join(parts)


async def _sync_article(story: ConsoleStory) -> None:
    """Create or update the public Article record for a published ConsoleStory."""
    from app.articles.models import Article
    from app.ai.cache import cache_invalidate_prefix

    marker = f"ptd:console:{story.id}"
    try:
        author_name = story.author.display_name or story.author.email  # type: ignore[union-attr]
    except Exception:
        author_name = ""
    try:
        author_avatar = story.author.avatar_url if story.author else None  # type: ignore[union-attr]
    except Exception:
        author_avatar = None

    content_html = _sections_to_html(story.sections or [])
    excerpt = story.standfirst or ""
    img = story.cover_image or ""
    category = story.category or "General"

    issue_cluster_id = story.issue_cluster_id or None

    existing = await Article.filter(source_url=marker).first()
    if existing:
        await existing.update_from_dict({
            "title": story.title or "",
            "excerpt": excerpt,
            "content": content_html,
            "category": category,
            "image_url": img,
            "author": author_name,
            "author_avatar": author_avatar,
            "is_featured": story.is_featured or False,
            "is_video": story.story_type == "video",
            "is_editorial_pick": story.is_editorial_pick or False,
            "is_premium": story.is_pay_worthy,
            "tags": story.tags or [],
            "issue_cluster_id": issue_cluster_id,
            "console_story_id": story.id,
        }).save()
        logger.info("Synced article update for story %s", story.id)
    else:
        suffix = str(story.id).replace("-", "")[:8]
        slug = _slugify(story.title or "untitled", suffix)
        counter = 1
        base = slug
        while await Article.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        await Article.create(
            slug=slug,
            title=story.title or "",
            excerpt=excerpt,
            content=content_html,
            category=category,
            image_url=img,
            author=author_name,
            author_avatar=author_avatar,
            source="Prime Times Daily",
            source_url=marker,
            is_internal=True,
            is_featured=story.is_featured or False,
            is_video=(story.story_type == "video"),
            is_editorial_pick=(story.is_editorial_pick or False),
            is_premium=story.is_pay_worthy,
            console_story_id=story.id,
            published_at=datetime.now(timezone.utc),
            tags=story.tags or [],
            issue_cluster_id=issue_cluster_id,
        )
        logger.info("Created public article for story %s (slug=%s)", story.id, slug)

    # Bust the feed cache so the new/updated article appears immediately
    await cache_invalidate_prefix("feed:")

router = APIRouter(prefix="/api/console", tags=["console"])

# Roles that can see & edit anyone's story
_EDITORIAL_ROLES = {UserRole.editor, UserRole.admin, UserRole.super_admin}
# Roles allowed to change status to "publish"
_PUBLISH_ROLES = {UserRole.editor, UserRole.admin, UserRole.super_admin}


def _require_writer(current_user: User = Depends(current_active_user)) -> User:
    if not role_has_at_least(current_user.role, UserRole.contributor):
        raise HTTPException(status_code=403, detail="Requires contributor role or above")
    return current_user


def _story_to_read(story: ConsoleStory) -> ConsoleStoryRead:
    sections_raw = story.sections or []
    sections = [SectionData.model_validate(s) for s in sections_raw]
    author = AuthorRead(
        id=str(story.author_id),
        display_name=story.author.display_name if hasattr(story, "author") and story.author else None,
        email=story.author.email if hasattr(story, "author") and story.author else "",
        role=story.author.role.value if hasattr(story, "author") and story.author and story.author.role else "",
    )
    return ConsoleStoryRead(
        id=str(story.id),
        author=author,
        title=story.title,
        standfirst=story.standfirst,
        sections=sections,
        cover_image=story.cover_image,
        category=story.category,
        tags=story.tags or [],
        story_type=story.story_type,
        status=story.status,
        scheduled_for=story.scheduled_for.isoformat() if story.scheduled_for else None,
        word_count=story.word_count,
        editor_note=story.editor_note,
        geo_regions=story.geo_regions or [],
        is_featured=story.is_featured or False,
        is_editorial_pick=story.is_editorial_pick or False,
        issue_cluster_id=str(story.issue_cluster_id) if story.issue_cluster_id else None,
        created_at=story.created_at.isoformat(),
        updated_at=story.updated_at.isoformat(),
    )


@router.get("/stories", response_model=list[ConsoleStoryRead])
async def list_stories(
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(_require_writer),
) -> list[ConsoleStoryRead]:
    """
    Returns stories the current user can see.
    Editors/admins/super_admins see all; reporters/contributors see only their own.
    """
    is_editorial = current_user.role in _EDITORIAL_ROLES

    qs = ConsoleStory.all().prefetch_related("author")
    if not is_editorial:
        qs = qs.filter(author_id=current_user.id)

    # Editorial roles: exclude other people's auto_drafts
    if is_editorial:
        qs = qs.exclude(
            status=ConsoleStoryStatus.auto_draft,
            author_id__not=current_user.id,
        )

    if status:
        try:
            qs = qs.filter(status=ConsoleStoryStatus(status))
        except ValueError:
            pass

    # Always hide trash from others
    if not is_editorial:
        qs = qs.exclude(status=ConsoleStoryStatus.trash)

    stories = await qs.order_by("-updated_at").offset(skip).limit(limit)
    return [_story_to_read(s) for s in stories]


@router.get("/stories/{story_id}", response_model=ConsoleStoryRead)
async def get_story(
    story_id: uuid.UUID,
    current_user: User = Depends(_require_writer),
) -> ConsoleStoryRead:
    story = await ConsoleStory.filter(id=story_id).prefetch_related("author").first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    is_editorial = current_user.role in _EDITORIAL_ROLES
    if not is_editorial and str(story.author_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your story")

    return _story_to_read(story)


@router.post("/stories", response_model=ConsoleStoryRead, status_code=201)
async def create_story(
    body: ConsoleStoryCreate,
    current_user: User = Depends(_require_writer),
) -> ConsoleStoryRead:
    # Writers can only create draft/auto_draft
    if current_user.role not in _EDITORIAL_ROLES:
        if body.status not in (
            ConsoleStoryStatus.auto_draft,
            ConsoleStoryStatus.draft,
            ConsoleStoryStatus.pending_review,
        ):
            body = body.model_copy(update={"status": ConsoleStoryStatus.auto_draft})

    story = await ConsoleStory.create(
        author_id=current_user.id,
        title=body.title,
        standfirst=body.standfirst,
        sections=[s.model_dump() for s in body.sections],
        cover_image=body.cover_image,
        category=body.category,
        tags=body.tags,
        story_type=body.story_type,
        status=body.status,
        word_count=body.word_count,
        editor_note=body.editor_note,
        geo_regions=body.geo_regions,
        is_featured=body.is_featured,
        is_editorial_pick=body.is_editorial_pick,
        issue_cluster_id=body.issue_cluster_id or None,
    )
    await story.fetch_related("author")
    return _story_to_read(story)


@router.patch("/stories/{story_id}", response_model=ConsoleStoryRead)
async def update_story(
    story_id: uuid.UUID,
    body: ConsoleStoryUpdate,
    current_user: User = Depends(_require_writer),
) -> ConsoleStoryRead:
    story = await ConsoleStory.filter(id=story_id).prefetch_related("author").first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    is_editorial = current_user.role in _EDITORIAL_ROLES
    if not is_editorial and str(story.author_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your story")

    # Non-editorial: can't set publish status
    if current_user.role not in _PUBLISH_ROLES:
        if body.status == ConsoleStoryStatus.publish:
            raise HTTPException(status_code=403, detail="Only editors can publish stories")

    update_data = {
        "title": body.title,
        "standfirst": body.standfirst,
        "sections": [s.model_dump() for s in body.sections],
        "cover_image": body.cover_image,
        "category": body.category,
        "tags": body.tags,
        "story_type": body.story_type,
        "status": body.status,
        "word_count": body.word_count,
        "geo_regions": body.geo_regions,
        "issue_cluster_id": body.issue_cluster_id or None,
    }
    if body.editor_note is not None and is_editorial:
        update_data["editor_note"] = body.editor_note
    # Only editors can set featured / editorial pick flags
    if is_editorial:
        update_data["is_featured"] = body.is_featured
        update_data["is_editorial_pick"] = body.is_editorial_pick

    # Stamp published_at on first publish.
    if update_data.get("status") == ConsoleStoryStatus.publish and not story.published_at:
        update_data["published_at"] = datetime.now(timezone.utc)

    old_status = story.status
    old_editor_note = story.editor_note
    await story.update_from_dict(update_data).save()
    await story.fetch_related("author")
    title_snippet = (story.title or "Untitled")[:80]
    # Keep the public Article in sync if this story is already published
    if update_data.get("status") == ConsoleStoryStatus.publish or story.status == ConsoleStoryStatus.publish:
        try:
            await _sync_article(story)
        except Exception as exc:
            logger.error("Failed to sync article for story %s: %s", story_id, exc)
        try:
            from app.contributors.service import on_story_published
            await on_story_published(story)
        except Exception as exc:
            logger.error("Failed contributor publish hook for story %s: %s", story_id, exc)
        if update_data.get("status") == ConsoleStoryStatus.publish and old_status != ConsoleStoryStatus.publish:
            await _notify_story(
                story, NotificationType.story_published,
                "Your story is now live",
                f'"{title_snippet}" has been published.',
                sender_id=current_user.id,
            )
    if (
        update_data.get("status") == ConsoleStoryStatus.pending_review
        and old_status != ConsoleStoryStatus.pending_review
    ):
        await _notify_story(
            story, NotificationType.story_in_review,
            "Story submitted for review",
            f'"{title_snippet}" is now in review.',
            sender_id=current_user.id,
        )
        author_name = (story.author.display_name or story.author.email) if story.author else "A contributor"
        await _notify_editorial_team(
            story, NotificationType.story_submitted,
            "Story ready for review",
            f'"{title_snippet}" by {author_name} is awaiting editorial review.',
            sender_id=current_user.id,
        )
    if body.editor_note is not None and is_editorial and body.editor_note != old_editor_note:
        await _notify_story(
            story, NotificationType.story_note,
            "Editor left a note on your story",
            f'"{title_snippet}": {body.editor_note[:120]}',
            sender_id=current_user.id,
        )
    return _story_to_read(story)


@router.patch("/stories/{story_id}/status", response_model=ConsoleStoryRead)
async def update_story_status(
    story_id: uuid.UUID,
    body: ConsoleStoryStatusUpdate,
    current_user: User = Depends(_require_writer),
) -> ConsoleStoryRead:
    story = await ConsoleStory.filter(id=story_id).prefetch_related("author").first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    is_editorial = current_user.role in _EDITORIAL_ROLES
    if not is_editorial and str(story.author_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your story")

    if body.status == ConsoleStoryStatus.publish and current_user.role not in _PUBLISH_ROLES:
        raise HTTPException(status_code=403, detail="Only editors can publish stories")

    old_status = story.status
    update: dict = {"status": body.status}
    if body.scheduled_for:
        update["scheduled_for"] = body.scheduled_for
    if body.editor_note is not None:
        update["editor_note"] = body.editor_note
    # Stamp published_at on first publish.
    if body.status == ConsoleStoryStatus.publish and not story.published_at:
        update["published_at"] = datetime.now(timezone.utc)

    await story.update_from_dict(update).save()
    await story.fetch_related("author")
    title_snippet = (story.title or "Untitled")[:80]
    if body.status == ConsoleStoryStatus.publish:
        try:
            await _sync_article(story)
        except Exception as exc:
            logger.error("Failed to sync article for story %s: %s", story_id, exc)
        try:
            from app.contributors.service import on_story_published
            await on_story_published(story)
        except Exception as exc:
            logger.error("Failed contributor publish hook for story %s: %s", story_id, exc)
        await _notify_story(
            story, NotificationType.story_published,
            "Your story is now live",
            f'"{title_snippet}" has been published.',
            sender_id=current_user.id,
        )
    elif body.status == ConsoleStoryStatus.pending_review and old_status != ConsoleStoryStatus.pending_review:
        await _notify_story(
            story, NotificationType.story_in_review,
            "Story submitted for review",
            f'"{title_snippet}" is now in review.',
            sender_id=current_user.id,
        )
        author_name = (story.author.display_name or story.author.email) if story.author else "A contributor"
        await _notify_editorial_team(
            story, NotificationType.story_submitted,
            "Story ready for review",
            f'"{title_snippet}" by {author_name} is awaiting editorial review.',
            sender_id=current_user.id,
        )
    elif body.status == ConsoleStoryStatus.draft and old_status == ConsoleStoryStatus.pending_review:
        note_str = f" Note: {body.editor_note[:120]}" if body.editor_note else ""
        await _notify_story(
            story, NotificationType.story_rejected,
            "Story returned for revisions",
            f'"{title_snippet}" has been sent back for revisions.{note_str}',
            sender_id=current_user.id,
        )
    elif body.status == ConsoleStoryStatus.draft and body.editor_note:
        await _notify_story(
            story, NotificationType.story_note,
            "Editor left a note on your story",
            f'"{title_snippet}": {body.editor_note[:120]}',
            sender_id=current_user.id,
        )
    return _story_to_read(story)


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    folder: str = Query("media", pattern=r"^[a-z0-9_-]{1,32}$"),
    current_user: User = Depends(_require_writer),
) -> dict:
    """Upload an image file to R2 and return its public URL."""
    from app.storage import ALLOWED_MIME_TYPES, MAX_UPLOAD_BYTES, is_r2_configured, upload_to_r2

    if not is_r2_configured():
        raise HTTPException(
            status_code=503,
            detail="Media storage not configured — add R2 credentials to .env",
        )

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=422, detail=f"File type '{content_type}' is not allowed")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large — maximum is 10 MB")

    url = await upload_to_r2(data, content_type, folder)
    return {"url": url}


@router.delete("/stories/{story_id}", status_code=204)
async def delete_story(
    story_id: uuid.UUID,
    current_user: User = Depends(_require_writer),
) -> None:
    story = await ConsoleStory.filter(id=story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    is_editorial = current_user.role in _EDITORIAL_ROLES
    if not is_editorial and str(story.author_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your story")

    # Super admins hard-delete; everyone else moves to trash
    if current_user.role == UserRole.super_admin:
        await story.delete()
    else:
        story.status = ConsoleStoryStatus.trash
        await story.save()


@router.post("/refresh-author-info")
async def refresh_author_info(
    current_user: User = Depends(_require_writer),
) -> dict:
    """Bulk-update author name and avatar on all the current user's published articles.

    Call this after changing your display name or avatar so the public article
    feed reflects your current profile immediately.
    """
    from app.articles.models import Article as PublicArticle

    author_name = current_user.display_name or current_user.email
    avatar_url = current_user.avatar_url

    story_ids = await ConsoleStory.filter(author_id=current_user.id).values_list("id", flat=True)
    if not story_ids:
        return {"updated": 0}

    count = await PublicArticle.filter(console_story_id__in=story_ids).update(
        author=author_name,
        author_avatar=avatar_url,
    )
    return {"updated": count}


# ── Issue cluster helpers ──────────────────────────────────────────────────────

def _require_editorial(current_user: User = Depends(current_active_user)) -> User:
    if current_user.role not in _EDITORIAL_ROLES:
        raise HTTPException(status_code=403, detail="Requires editor role or above")
    return current_user


def _slugify_issue(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:200]


async def _issue_to_read(cluster: IssueCluster) -> IssueClusterRead:
    story_count = await ConsoleStory.filter(
        issue_cluster_id=cluster.id
    ).exclude(status=ConsoleStoryStatus.trash).count()

    assigned_editor = None
    if cluster.assigned_editor_id:
        try:
            editor = await User.get(id=cluster.assigned_editor_id)
            assigned_editor = AssignedEditorRead(
                id=str(editor.id),
                display_name=editor.display_name,
                email=editor.email,
            )
        except Exception:
            pass

    return IssueClusterRead(
        id=str(cluster.id),
        name=cluster.name,
        slug=cluster.slug,
        description=cluster.description,
        category=cluster.category,
        status=cluster.status.value,
        breaking_order=cluster.breaking_order,
        breaking_expires_at=cluster.breaking_expires_at.isoformat() if cluster.breaking_expires_at else None,
        cover_image=cluster.cover_image,
        story_count=story_count,
        created_by_id=str(cluster.created_by_id),
        assigned_editor=assigned_editor,
        created_at=cluster.created_at.isoformat(),
        updated_at=cluster.updated_at.isoformat(),
    )


async def _sync_breaking_nav(cluster: IssueCluster) -> None:
    """Auto-manage NavMenu breaking entry when a cluster's status changes."""
    nav_slug = f"breaking-issue-{cluster.slug}"
    if cluster.status == IssueClusterStatus.breaking:
        existing = await NavMenu.filter(slug=nav_slug).first()
        if existing:
            existing.label = cluster.name
            existing.href = f"/issues/{cluster.slug}"
            existing.position = cluster.breaking_order or 100
            existing.is_active = True
            await existing.save()
        else:
            await NavMenu.create(
                label=cluster.name,
                slug=nav_slug,
                href=f"/issues/{cluster.slug}",
                area=NavArea.main,
                item_type=NavItemType.breaking,
                position=cluster.breaking_order or 100,
                is_active=True,
            )
    else:
        await NavMenu.filter(slug=nav_slug).update(is_active=False)


# ── Issue cluster endpoints ────────────────────────────────────────────────────

@router.get("/issues", response_model=list[IssueClusterRead])
async def list_issues(
    status: Optional[str] = Query(None),
    current_user: User = Depends(_require_writer),
) -> list[IssueClusterRead]:
    qs = IssueCluster.all()
    if status:
        qs = qs.filter(status=status)
    clusters = await qs.order_by("-updated_at")
    return [await _issue_to_read(c) for c in clusters]


@router.post("/issues", response_model=IssueClusterRead, status_code=201)
async def create_issue(
    body: IssueClusterCreate,
    current_user: User = Depends(_require_editorial),
) -> IssueClusterRead:
    slug = body.slug.strip() if body.slug.strip() else _slugify_issue(body.name)
    # Ensure slug uniqueness
    base = slug
    counter = 1
    while await IssueCluster.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1

    from datetime import datetime as _dt
    expires_at = None
    if body.breaking_expires_at:
        try:
            expires_at = _dt.fromisoformat(body.breaking_expires_at)
        except ValueError:
            pass

    cluster = await IssueCluster.create(
        name=body.name,
        slug=slug,
        description=body.description,
        category=body.category,
        status=body.status,
        breaking_order=body.breaking_order,
        breaking_expires_at=expires_at,
        cover_image=body.cover_image,
        created_by_id=current_user.id,
        assigned_editor_id=body.assigned_editor_id or None,
    )
    await _sync_breaking_nav(cluster)
    return await _issue_to_read(cluster)


@router.get("/issues/{issue_id}", response_model=IssueClusterRead)
async def get_issue(
    issue_id: uuid.UUID,
    current_user: User = Depends(_require_writer),
) -> IssueClusterRead:
    cluster = await IssueCluster.filter(id=issue_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Issue cluster not found")
    return await _issue_to_read(cluster)


@router.patch("/issues/{issue_id}", response_model=IssueClusterRead)
async def update_issue(
    issue_id: uuid.UUID,
    body: IssueClusterUpdate,
    current_user: User = Depends(_require_editorial),
) -> IssueClusterRead:
    cluster = await IssueCluster.filter(id=issue_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Issue cluster not found")

    from datetime import datetime as _dt
    if body.name is not None:
        cluster.name = body.name
    if body.description is not None:
        cluster.description = body.description
    if body.category is not None:
        cluster.category = body.category
    if body.status is not None:
        cluster.status = body.status
    if body.breaking_order is not None:
        cluster.breaking_order = body.breaking_order
    if body.breaking_expires_at is not None:
        try:
            cluster.breaking_expires_at = _dt.fromisoformat(body.breaking_expires_at)  # type: ignore[assignment]
        except ValueError:
            cluster.breaking_expires_at = None  # type: ignore[assignment]
    if body.cover_image is not None:
        cluster.cover_image = body.cover_image
    if body.assigned_editor_id is not None:
        cluster.assigned_editor_id = body.assigned_editor_id or None  # type: ignore[assignment]

    await cluster.save()
    await _sync_breaking_nav(cluster)
    return await _issue_to_read(cluster)


@router.delete("/issues/{issue_id}", status_code=204)
async def delete_issue(
    issue_id: uuid.UUID,
    current_user: User = Depends(_require_editorial),
) -> None:
    cluster = await IssueCluster.filter(id=issue_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Issue cluster not found")
    # Remove the associated breaking nav entry so the main site nav stays clean
    await NavMenu.filter(slug=f"breaking-issue-{cluster.slug}").delete()
    await cluster.delete()


@router.get("/issues/{issue_id}/stories", response_model=list[ConsoleStoryRead])
async def list_issue_stories(
    issue_id: uuid.UUID,
    current_user: User = Depends(_require_writer),
) -> list[ConsoleStoryRead]:
    cluster = await IssueCluster.filter(id=issue_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Issue cluster not found")
    stories = await ConsoleStory.filter(
        issue_cluster_id=issue_id
    ).exclude(status=ConsoleStoryStatus.trash).prefetch_related("author").order_by("-updated_at")
    return [_story_to_read(s) for s in stories]


@router.get("/portfolio")
async def get_portfolio(current_user: User = Depends(current_active_user)):
    """The signed-in writer's published work with engagement metrics.

    Returns every published Article that originated from one of the writer's
    ConsoleStories, including views, successful shares, and helpful yes/no
    feedback. The frontend handles search / time-window / sort / category.
    """
    story_type_by_id = {
        s["id"]: s["story_type"]
        for s in await ConsoleStory.filter(
            author_id=current_user.id, status=ConsoleStoryStatus.publish
        ).values("id", "story_type")
    }
    if not story_type_by_id:
        return []

    articles = (
        await Article.filter(console_story_id__in=list(story_type_by_id.keys()))
        .order_by("-published_at")
    )

    return [
        {
            "id": str(a.id),
            "slug": a.slug,
            "title": a.title,
            "excerpt": a.excerpt,
            "category": a.category,
            "story_type": story_type_by_id.get(a.console_story_id, "article"),
            "image": a.image_url,
            "published_at": a.published_at.isoformat(),
            "views": a.view_count,
            "shares": a.share_count,
            "helpful_yes": a.helpful_yes,
            "helpful_no": a.helpful_no,
        }
        for a in articles
    ]
