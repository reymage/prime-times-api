"""
Console story endpoints — editorial workflow for writers and editors.

Role visibility:
  reporter / contributor  → own stories only
  editor / admin / super_admin → all stories
"""
import html
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.auth.dependencies import current_active_user
from app.auth.models import User
from app.articles.models import Article
from app.console.models import (
    ConsoleStory,
    ConsoleStoryStatus,
    IssueCluster,
    IssueClusterStatus,
    StoryComment,
)
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
    StoryAssignUpdate,
    StoryCommentCreate,
    StoryCommentAuthorRead,
    StoryCommentRead,
    StoryCommentResolve,
)
from app.core.roles import UserRole, role_has_at_least
from app.notifications.models import Notification, NotificationType
from app.notifications.service import create_notification

logger = logging.getLogger(__name__)


def _byline_user_id(story: "ConsoleStory") -> uuid.UUID | None:
    """The user the story is attributed to (the writer).

    An editor can initiate a story and assign it to a writer; in that case the
    assignee owns the byline. Otherwise it's the record creator (`author`).
    """
    return story.assigned_to_id or story.author_id


async def _notify_story(
    story: "ConsoleStory",
    notif_type: NotificationType,
    title: str,
    body: str,
    sender_id: uuid.UUID | None = None,
) -> None:
    """Fire a notification to the story's byline writer; swallow all errors."""
    try:
        recipient_id = _byline_user_id(story)
        if recipient_id and str(recipient_id) != str(sender_id):
            await create_notification(
                recipient_id=recipient_id,
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
    """Notify all active editors/admins about a story event; swallow all errors.

    Filters by role in the database and writes the notifications in a single
    bulk insert rather than one round-trip per editor.
    """
    try:
        editorial_roles = [
            UserRole.editor.value,
            UserRole.admin.value,
            UserRole.super_admin.value,
        ]
        editor_ids = await User.filter(
            is_active=True, role__in=editorial_roles
        ).values_list("id", flat=True)
        notifs = [
            Notification(
                recipient_id=editor_id,
                sender_id=sender_id,
                notif_type=notif_type,
                title=title,
                body=body,
                link="/console/reviews",
            )
            for editor_id in editor_ids
            if str(editor_id) != str(sender_id)
        ]
        if notifs:
            await Notification.bulk_create(notifs)
    except Exception as exc:
        logger.warning("editorial notification failed for story %s: %s", story.id, exc)


def _check_version(story: "ConsoleStory", expected_version: int | None) -> None:
    """Optimistic-lock guard: reject a save built on a stale copy of the story.

    The client sends the ``version`` it last saw; if the story has moved on
    (someone else saved in the meantime) we 409 instead of silently clobbering.
    """
    if expected_version is not None and expected_version != (story.version or 1):
        raise HTTPException(
            status_code=409,
            detail=(
                "This story was changed by someone else since you opened it. "
                "Reload to see the latest version before saving."
            ),
        )


async def _post_editorial_note(
    story: "ConsoleStory",
    author_id: uuid.UUID,
    note: str | None,
    *,
    notify: bool = True,
) -> None:
    """Record an editorial note as a comment in the story's thread.

    The thread is the single canonical home for editorial notes (the legacy
    ``editor_note`` column is no longer written). When ``notify`` is True the
    story author gets a generic comment notification; callers that already fire
    a more specific notification (e.g. changes-requested) pass ``notify=False``.
    """
    clean = (note or "").strip()
    if not clean:
        return
    try:
        await StoryComment.create(
            story_id=story.id,
            author_id=author_id,
            body=html.escape(clean[:5000]),
        )
        if notify:
            title_snippet = (story.title or "Untitled")[:80]
            await _notify_story(
                story, NotificationType.story_comment,
                "New comment on your story",
                f'"{title_snippet}": {clean[:120]}',
                sender_id=author_id,
            )
    except Exception as exc:
        logger.warning("failed to post editorial note for story %s: %s", story.id, exc)


async def _resolve_open_comments(story_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Mark every open comment on a story as resolved.

    Called when the writer resubmits for review or the story is published — both
    natural points where the outstanding back-and-forth has been addressed, so
    the open-comment count shouldn't linger.
    """
    try:
        await StoryComment.filter(story_id=story_id, is_resolved=False).update(
            is_resolved=True,
            resolved_by_id=user_id,
            resolved_at=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.warning("failed to resolve open comments for story %s: %s", story_id, exc)


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

    from app.auth.models import User
    from app.auth.slugs import ensure_user_slug

    marker = f"ptd:console:{story.id}"
    # Attribute the article to the byline writer (assignee if commissioned, else
    # the record author). Resolve that user for the cached name/avatar/slug.
    byline_id = _byline_user_id(story)
    byline_user = None
    if byline_id and byline_id == story.author_id and getattr(story, "author", None):
        byline_user = story.author  # already prefetched
    elif byline_id:
        byline_user = await User.get_or_none(id=byline_id)
    author_name = ""
    author_avatar = None
    author_slug = None
    if byline_user:
        author_name = byline_user.display_name or byline_user.email
        author_avatar = byline_user.avatar_url
        try:
            author_slug = await ensure_user_slug(byline_user)
        except Exception:
            author_slug = byline_user.slug

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
            "author_id": byline_id,
            "author_slug": author_slug,
            "is_featured": story.is_featured or False,
            "is_video": story.story_type == "video",
            "is_editorial_pick": story.is_editorial_pick or False,
            "is_premium": story.is_pay_worthy,
            "tags": story.tags or [],
            "issue_cluster_id": issue_cluster_id,
            "console_story_id": story.id,
        }).save()
        article_slug = existing.slug
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
            author_id=byline_id,
            author_slug=author_slug,
            source="Wire24",
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
        article_slug = slug
        logger.info("Created public article for story %s (slug=%s)", story.id, slug)

    # Bust the feed cache so the new/updated article appears immediately
    await cache_invalidate_prefix("feed:")

    # Purge Cloudflare's edge cache for the public surfaces this article appears
    # on, so a publish/edit shows up immediately instead of waiting for the TTL.
    from app.core.cache_purge import purge_article
    await purge_article(article_slug, category)

router = APIRouter(prefix="/api/console", tags=["console"])

# Roles that can see & edit anyone's story
_EDITORIAL_ROLES = {UserRole.editor, UserRole.admin, UserRole.super_admin}
# Roles allowed to change status to "publish"
_PUBLISH_ROLES = {UserRole.editor, UserRole.admin, UserRole.super_admin}


def _require_writer(current_user: User = Depends(current_active_user)) -> User:
    if not role_has_at_least(current_user.role, UserRole.contributor):
        raise HTTPException(status_code=403, detail="Requires contributor role or above")
    return current_user


def _can_access_story(story: "ConsoleStory", user: User) -> bool:
    """Who may see/edit a story: any editorial role, the record author, or the
    writer it's been assigned to."""
    if user.role in _EDITORIAL_ROLES:
        return True
    uid = str(user.id)
    return uid == str(story.author_id) or uid == str(story.assigned_to_id)


def _opt_person(story: ConsoleStory, attr: str) -> AuthorRead | None:
    """Build an AuthorRead from a (possibly unfetched) related user; None-safe."""
    try:
        rel = getattr(story, attr)
    except Exception:
        return None
    if not rel:
        return None
    return AuthorRead(
        id=str(rel.id),
        display_name=rel.display_name,
        email=rel.email or "",
        role=rel.role.value if rel.role else "",
    )


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
        assigned_to=_opt_person(story, "assigned_to"),
        last_edited_by=_opt_person(story, "last_edited_by"),
        last_edited_at=story.last_edited_at.isoformat() if story.last_edited_at else None,
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
        version=story.version or 1,
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

    qs = ConsoleStory.all().prefetch_related("author", "assigned_to", "last_edited_by")
    if not is_editorial:
        # Own stories plus anything assigned to them by an editor.
        from tortoise.expressions import Q
        qs = qs.filter(Q(author_id=current_user.id) | Q(assigned_to_id=current_user.id))

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
    story = await ConsoleStory.filter(id=story_id).prefetch_related("author", "assigned_to", "last_edited_by").first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    is_editorial = current_user.role in _EDITORIAL_ROLES
    if not _can_access_story(story, current_user):
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
        geo_regions=body.geo_regions,
        is_featured=body.is_featured,
        is_editorial_pick=body.is_editorial_pick,
        issue_cluster_id=body.issue_cluster_id or None,
    )
    await story.fetch_related("author", "assigned_to", "last_edited_by")
    return _story_to_read(story)


@router.patch("/stories/{story_id}", response_model=ConsoleStoryRead)
async def update_story(
    story_id: uuid.UUID,
    body: ConsoleStoryUpdate,
    current_user: User = Depends(_require_writer),
) -> ConsoleStoryRead:
    story = await ConsoleStory.filter(id=story_id).prefetch_related("author", "assigned_to", "last_edited_by").first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    is_editorial = current_user.role in _EDITORIAL_ROLES
    if not _can_access_story(story, current_user):
        raise HTTPException(status_code=403, detail="Not your story")

    # Non-editorial: can't set publish or changes_requested (editor-only states)
    if current_user.role not in _PUBLISH_ROLES:
        if body.status == ConsoleStoryStatus.publish:
            raise HTTPException(status_code=403, detail="Only editors can publish stories")
        if body.status == ConsoleStoryStatus.changes_requested:
            raise HTTPException(
                status_code=403,
                detail="Only editors can request changes on a story",
            )

    # Reject a save built on a stale copy (someone else saved in the meantime).
    _check_version(story, body.expected_version)

    # An editor saving content changes on a story they're not the byline writer
    # of is a silent edit the writer should be told about (and audited).
    editor_editing_others = is_editorial and str(_byline_user_id(story)) != str(current_user.id)
    # Normalize the stored copy through the SAME validators the incoming body
    # passed through, so the diff compares like-for-like. The stored values were
    # already sanitized/escaped once on a prior save; the body re-escapes the
    # same input, so an unchanged field must be normalized on both sides or it
    # spuriously looks "edited" (e.g. a title containing & < > ' ").
    _prev_norm = ConsoleStoryCreate(
        title=story.title or "",
        standfirst=story.standfirst or "",
        sections=[SectionData.model_validate(s) for s in (story.sections or [])],
    )
    prev_sections = [s.model_dump() for s in _prev_norm.sections]
    prev_title = _prev_norm.title
    prev_standfirst = _prev_norm.standfirst

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
        # Bump the optimistic-lock counter on every save.
        "version": (story.version or 1) + 1,
    }
    # Only editors can set featured / editorial pick flags
    if is_editorial:
        update_data["is_featured"] = body.is_featured
        update_data["is_editorial_pick"] = body.is_editorial_pick

    # Did the actual story content change? (drives notify-on-edit + audit)
    content_changed = (
        update_data["sections"] != prev_sections
        or update_data["title"] != prev_title
        or update_data["standfirst"] != prev_standfirst
    )
    if editor_editing_others and content_changed:
        update_data["last_edited_by_id"] = current_user.id
        update_data["last_edited_at"] = datetime.now(timezone.utc)

    # Stamp published_at on first publish.
    if update_data.get("status") == ConsoleStoryStatus.publish and not story.published_at:
        update_data["published_at"] = datetime.now(timezone.utc)

    old_status = story.status
    new_status = update_data.get("status")
    await story.update_from_dict(update_data).save()
    await story.fetch_related("author", "assigned_to", "last_edited_by")
    title_snippet = (story.title or "Untitled")[:80]
    note = (body.editor_note or "").strip() if is_editorial else ""
    # Keep the public Article in sync if this story is already published
    if new_status == ConsoleStoryStatus.publish or story.status == ConsoleStoryStatus.publish:
        try:
            await _sync_article(story)
        except Exception as exc:
            logger.error("Failed to sync article for story %s: %s", story_id, exc)
        try:
            from app.contributors.service import on_story_published
            await on_story_published(story)
        except Exception as exc:
            logger.error("Failed contributor publish hook for story %s: %s", story_id, exc)
        if new_status == ConsoleStoryStatus.publish and old_status != ConsoleStoryStatus.publish:
            await _resolve_open_comments(story.id, current_user.id)
            await _notify_story(
                story, NotificationType.story_published,
                "Your story is now live",
                f'"{title_snippet}" has been published.',
                sender_id=current_user.id,
            )
    if (
        new_status == ConsoleStoryStatus.pending_review
        and old_status != ConsoleStoryStatus.pending_review
    ):
        # Writer resubmitting after a round of notes — clear the open thread.
        await _resolve_open_comments(story.id, current_user.id)
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
    if (
        new_status == ConsoleStoryStatus.changes_requested
        and old_status != ConsoleStoryStatus.changes_requested
    ):
        # The note lives in the thread; the status notification covers the alert.
        await _post_editorial_note(story, current_user.id, note, notify=False)
        note_str = f" Note: {note[:120]}" if note else ""
        await _notify_story(
            story, NotificationType.story_changes_requested,
            "Changes requested on your story",
            f'"{title_snippet}" needs changes before it can be published.{note_str}',
            sender_id=current_user.id,
        )
    elif note:
        # A plain editorial note on any other transition → canonical thread.
        await _post_editorial_note(story, current_user.id, note, notify=True)
    # Notify the writer when an editor silently edits their story's content
    # (no status/note change would otherwise tell them their words changed).
    if editor_editing_others:
        if content_changed:
            # Debounce: an editor working through a story autosaves many times.
            # Collapse the whole session into one notification — skip if the
            # writer still has an unread "edited" ping from this editor on this
            # story. Once they've read it, a later edit notifies afresh.
            already_pinged = await Notification.filter(
                recipient_id=story.author_id,
                sender_id=current_user.id,
                notif_type=NotificationType.story_edited,
                link=f"/console/editor/{story.id}",
                is_read=False,
            ).exists()
            if not already_pinged:
                await _notify_story(
                    story, NotificationType.story_edited,
                    "An editor edited your story",
                    f'"{title_snippet}" was edited by the desk.',
                    sender_id=current_user.id,
                )
    return _story_to_read(story)


@router.patch("/stories/{story_id}/status", response_model=ConsoleStoryRead)
async def update_story_status(
    story_id: uuid.UUID,
    body: ConsoleStoryStatusUpdate,
    current_user: User = Depends(_require_writer),
) -> ConsoleStoryRead:
    story = await ConsoleStory.filter(id=story_id).prefetch_related("author", "assigned_to", "last_edited_by").first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    is_editorial = current_user.role in _EDITORIAL_ROLES
    if not _can_access_story(story, current_user):
        raise HTTPException(status_code=403, detail="Not your story")

    if body.status == ConsoleStoryStatus.publish and current_user.role not in _PUBLISH_ROLES:
        raise HTTPException(status_code=403, detail="Only editors can publish stories")
    if body.status == ConsoleStoryStatus.changes_requested and current_user.role not in _PUBLISH_ROLES:
        raise HTTPException(status_code=403, detail="Only editors can request changes on a story")

    # Reject a transition built on a stale copy of the story.
    _check_version(story, body.expected_version)

    old_status = story.status
    update: dict = {"status": body.status, "version": (story.version or 1) + 1}
    if body.scheduled_for:
        update["scheduled_for"] = body.scheduled_for
    # Stamp published_at on first publish.
    if body.status == ConsoleStoryStatus.publish and not story.published_at:
        update["published_at"] = datetime.now(timezone.utc)

    await story.update_from_dict(update).save()
    await story.fetch_related("author", "assigned_to", "last_edited_by")
    title_snippet = (story.title or "Untitled")[:80]
    # Editorial notes always go to the canonical thread, never the legacy column.
    note = (body.editor_note or "").strip() if is_editorial else ""
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
        await _resolve_open_comments(story.id, current_user.id)
        await _notify_story(
            story, NotificationType.story_published,
            "Your story is now live",
            f'"{title_snippet}" has been published.',
            sender_id=current_user.id,
        )
    elif body.status == ConsoleStoryStatus.pending_review and old_status != ConsoleStoryStatus.pending_review:
        # Writer resubmitting after a round of notes — clear the open thread.
        await _resolve_open_comments(story.id, current_user.id)
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
    elif body.status == ConsoleStoryStatus.changes_requested and old_status != ConsoleStoryStatus.changes_requested:
        # The note lives in the thread; the status notification covers the alert.
        await _post_editorial_note(story, current_user.id, note, notify=False)
        note_str = f" Note: {note[:120]}" if note else ""
        await _notify_story(
            story, NotificationType.story_changes_requested,
            "Changes requested on your story",
            f'"{title_snippet}" needs changes before it can be published.{note_str}',
            sender_id=current_user.id,
        )
    elif body.status == ConsoleStoryStatus.draft and old_status == ConsoleStoryStatus.pending_review:
        await _post_editorial_note(story, current_user.id, note, notify=False)
        note_str = f" Note: {note[:120]}" if note else ""
        await _notify_story(
            story, NotificationType.story_rejected,
            "Story returned for revisions",
            f'"{title_snippet}" has been sent back for revisions.{note_str}',
            sender_id=current_user.id,
        )
    elif note:
        # A plain editorial note on any other transition → canonical thread.
        await _post_editorial_note(story, current_user.id, note, notify=True)
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
    if not _can_access_story(story, current_user):
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


@router.patch("/stories/{story_id}/assign", response_model=ConsoleStoryRead)
async def assign_story(
    story_id: uuid.UUID,
    body: StoryAssignUpdate,
    current_user: User = Depends(_require_writer),
) -> ConsoleStoryRead:
    """Editor initiates/commissions a story to a writer. The assignee becomes the
    byline owner, can see/edit it, and is notified. Empty assignee_id unassigns.
    """
    if current_user.role not in _EDITORIAL_ROLES:
        raise HTTPException(status_code=403, detail="Only editors can assign stories")

    story = await ConsoleStory.filter(id=story_id).prefetch_related(
        "author", "assigned_to", "last_edited_by"
    ).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    assignee = None
    if body.assignee_id:
        assignee = await User.get_or_none(id=body.assignee_id)
        if not assignee or not assignee.is_active:
            raise HTTPException(status_code=404, detail="Assignee not found")
        if not role_has_at_least(assignee.role, UserRole.contributor):
            raise HTTPException(status_code=422, detail="Assignee must be a contributor or above")

    already_assigned = str(story.assigned_to_id or "")
    story.assigned_to_id = assignee.id if assignee else None
    await story.save(update_fields=["assigned_to_id", "updated_at"])
    await story.fetch_related("author", "assigned_to", "last_edited_by")

    # Notify the newly assigned writer (skip re-assigns to the same person / self).
    if assignee and str(assignee.id) != already_assigned and str(assignee.id) != str(current_user.id):
        title_snippet = (story.title or "Untitled")[:80]
        commissioner = current_user.display_name or current_user.email
        try:
            await create_notification(
                recipient_id=assignee.id,
                notif_type=NotificationType.story_assigned,
                title="You've been assigned a story",
                body=f'{commissioner} assigned "{title_snippet}" to you to write.',
                link=f"/console/editor/{story.id}",
                sender_id=current_user.id,
            )
        except Exception as exc:
            logger.warning("assign notification failed for story %s: %s", story.id, exc)

    return _story_to_read(story)


@router.get("/assignable-writers")
async def list_assignable_writers(
    current_user: User = Depends(_require_writer),
) -> list[dict]:
    """Active writers an editor can assign a story to (editorial only)."""
    if current_user.role not in _EDITORIAL_ROLES:
        raise HTTPException(status_code=403, detail="Only editors can list assignable writers")
    writer_roles = [
        UserRole.contributor.value,
        UserRole.columnist.value,
        UserRole.reporter.value,
        UserRole.editor.value,
    ]
    users = await User.filter(is_active=True, role__in=writer_roles).order_by("display_name").values(
        "id", "display_name", "email", "role"
    )
    return [
        {"id": str(u["id"]), "display_name": u["display_name"], "email": u["email"], "role": u["role"]}
        for u in users
    ]


# ── Story comment (editorial thread) endpoints ─────────────────────────────────

async def _load_story_for_thread(story_id: uuid.UUID, current_user: User) -> ConsoleStory:
    """Fetch a story and assert the user may read/post on its comment thread.

    Same visibility rule as the story itself: the author or any editorial role.
    """
    story = await ConsoleStory.filter(id=story_id).prefetch_related("author", "assigned_to", "last_edited_by").first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    if not _can_access_story(story, current_user):
        raise HTTPException(status_code=403, detail="Not your story")
    return story


def _comment_to_read(comment: StoryComment) -> StoryCommentRead:
    author = comment.author
    return StoryCommentRead(
        id=str(comment.id),
        story_id=str(comment.story_id),
        author=StoryCommentAuthorRead(
            id=str(comment.author_id),
            display_name=author.display_name if author else None,
            email=author.email if author else "",
            role=author.role.value if author and author.role else "",
        ),
        body=comment.body,
        is_resolved=comment.is_resolved,
        resolved_by_id=str(comment.resolved_by_id) if comment.resolved_by_id else None,
        resolved_at=comment.resolved_at.isoformat() if comment.resolved_at else None,
        created_at=comment.created_at.isoformat(),
        updated_at=comment.updated_at.isoformat(),
    )


@router.get("/stories/{story_id}/comments", response_model=list[StoryCommentRead])
async def list_story_comments(
    story_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(_require_writer),
) -> list[StoryCommentRead]:
    await _load_story_for_thread(story_id, current_user)
    comments = await (
        StoryComment.filter(story_id=story_id)
        .prefetch_related("author")
        .order_by("created_at")
        .offset(skip)
        .limit(limit)
    )
    return [_comment_to_read(c) for c in comments]


@router.post("/stories/{story_id}/comments", response_model=StoryCommentRead, status_code=201)
async def create_story_comment(
    story_id: uuid.UUID,
    body: StoryCommentCreate,
    current_user: User = Depends(_require_writer),
) -> StoryCommentRead:
    story = await _load_story_for_thread(story_id, current_user)

    comment = await StoryComment.create(
        story_id=story_id,
        author_id=current_user.id,
        body=body.body,
    )
    comment.author = current_user  # avoid an extra fetch for the response

    title_snippet = (story.title or "Untitled")[:80]
    commenter_name = current_user.display_name or current_user.email
    is_editorial = current_user.role in _EDITORIAL_ROLES
    if is_editorial and str(story.author_id) != str(current_user.id):
        # Editor → writer: notify the story's author.
        await _notify_story(
            story, NotificationType.story_comment,
            "New comment on your story",
            f'{commenter_name} on "{title_snippet}": {body.body[:120]}',
            sender_id=current_user.id,
        )
    else:
        # Writer (or self) → desk: notify the editorial team so the reply surfaces.
        await _notify_editorial_team(
            story, NotificationType.story_comment,
            "New comment on a story",
            f'{commenter_name} on "{title_snippet}": {body.body[:120]}',
            sender_id=current_user.id,
        )
    return _comment_to_read(comment)


@router.patch("/stories/{story_id}/comments/{comment_id}", response_model=StoryCommentRead)
async def resolve_story_comment(
    story_id: uuid.UUID,
    comment_id: uuid.UUID,
    body: StoryCommentResolve,
    current_user: User = Depends(_require_writer),
) -> StoryCommentRead:
    await _load_story_for_thread(story_id, current_user)
    comment = await StoryComment.filter(id=comment_id, story_id=story_id).prefetch_related("author").first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    comment.is_resolved = body.is_resolved
    if body.is_resolved:
        comment.resolved_by_id = current_user.id
        comment.resolved_at = datetime.now(timezone.utc)
    else:
        comment.resolved_by_id = None
        comment.resolved_at = None
    await comment.save()
    return _comment_to_read(comment)


@router.delete("/stories/{story_id}/comments/{comment_id}", status_code=204)
async def delete_story_comment(
    story_id: uuid.UUID,
    comment_id: uuid.UUID,
    current_user: User = Depends(_require_writer),
) -> None:
    await _load_story_for_thread(story_id, current_user)
    comment = await StoryComment.filter(id=comment_id, story_id=story_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    # Only the comment's own author or an editorial role can remove it.
    is_editorial = current_user.role in _EDITORIAL_ROLES
    if not is_editorial and str(comment.author_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Cannot delete another user's comment")
    await comment.delete()


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
    ).exclude(status=ConsoleStoryStatus.trash).prefetch_related("author", "assigned_to", "last_edited_by").order_by("-updated_at")
    return [_story_to_read(s) for s in stories]


@router.get("/portfolio")
async def get_portfolio(current_user: User = Depends(current_active_user)):
    """The signed-in writer's published work with engagement metrics.

    Returns every published Article that originated from one of the writer's
    ConsoleStories, including views, successful shares, and helpful yes/no
    feedback. The frontend handles search / time-window / sort / category.
    """
    # The writer's byline stories: those assigned to them, plus their own
    # unassigned stories (byline = assignee if set, else author).
    from tortoise.expressions import Q
    story_type_by_id = {
        s["id"]: s["story_type"]
        for s in await ConsoleStory.filter(status=ConsoleStoryStatus.publish)
        .filter(
            Q(assigned_to_id=current_user.id)
            | Q(assigned_to_id__isnull=True, author_id=current_user.id)
        )
        .values("id", "story_type")
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
            # Unique readers ("how many people viewed"), not raw load count.
            "views": a.unique_view_count,
            "shares": a.share_count,
            "helpful_yes": a.helpful_yes,
            "helpful_no": a.helpful_no,
        }
        for a in articles
    ]
