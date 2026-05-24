"""
Console story endpoints — editorial workflow for writers and editors.

Role visibility:
  reporter / contributor  → own stories only
  editor / admin / super_admin → all stories
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.auth.dependencies import current_active_user
from app.auth.models import User
from app.console.models import ConsoleStory, ConsoleStoryStatus
from app.console.schemas import (
    AuthorRead,
    ConsoleStoryCreate,
    ConsoleStoryRead,
    ConsoleStoryStatusUpdate,
    ConsoleStoryUpdate,
    SectionData,
)
from app.core.roles import UserRole, role_has_at_least

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
        role=str(story.author.role) if hasattr(story, "author") and story.author else "",
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
    }
    if body.editor_note is not None and is_editorial:
        update_data["editor_note"] = body.editor_note

    await story.update_from_dict(update_data).save()
    await story.fetch_related("author")
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

    update: dict = {"status": body.status}
    if body.scheduled_for:
        update["scheduled_for"] = body.scheduled_for
    if body.editor_note is not None:
        update["editor_note"] = body.editor_note

    await story.update_from_dict(update).save()
    await story.fetch_related("author")
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
