"""
DB-backed tests for the editor <-> writer back-and-forth workflow.

Exercises the console router functions directly against an in-memory SQLite
database (no HTTP / auth plumbing), covering the four pieces added:

  - Optimistic concurrency guard (stale save -> 409)
  - changes_requested status + its notification
  - Notify-on-edit when an editor edits someone else's story
  - Threaded story comments + cross-side notifications
"""
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from tortoise import Tortoise

from app.auth.models import User
from app.core.roles import UserRole
from app.console import router as console
from app.console.models import ConsoleStory, ConsoleStoryStatus, StoryComment
from app.console.schemas import (
    ConsoleStoryUpdate,
    ConsoleStoryStatusUpdate,
    SectionData,
    StoryCommentCreate,
    StoryCommentResolve,
)
from app.notifications.models import Notification, NotificationType

# The full, FK-consistent model set (mirrors app.database.TORTOISE_ORM).
_MODELS = [
    "app.auth.models",
    "app.nav.models",
    "app.articles.models",
    "app.gating.models",
    "app.ai.models",
    "app.console.models",
    "app.contributors.models",
    "app.notifications.models",
]


@pytest_asyncio.fixture
async def db():
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": _MODELS})
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


async def _make_user(role: UserRole, name: str, is_active: bool = True) -> User:
    return await User.create(
        email=f"{name}-{uuid.uuid4().hex[:8]}@test.dev",
        hashed_password="x",
        role=role,
        display_name=name,
        is_active=is_active,
    )


async def _make_story(author: User, **kw) -> ConsoleStory:
    defaults = dict(
        title="Test Story",
        standfirst="A standfirst",
        sections=[{"id": "s1", "type": "text", "heading": "", "content": "original body"}],
        status=ConsoleStoryStatus.pending_review,
    )
    defaults.update(kw)
    story = await ConsoleStory.create(author_id=author.id, **defaults)
    await story.fetch_related("author")
    return story


def _update_body(story: ConsoleStory, **overrides) -> ConsoleStoryUpdate:
    data = dict(
        title=story.title,
        standfirst=story.standfirst,
        sections=[SectionData.model_validate(s) for s in (story.sections or [])],
        cover_image=story.cover_image,
        category=story.category,
        tags=story.tags or [],
        story_type=story.story_type,
        status=story.status,
        word_count=story.word_count,
        geo_regions=story.geo_regions or [],
        is_featured=story.is_featured,
        is_editorial_pick=story.is_editorial_pick,
        issue_cluster_id=None,
    )
    data.update(overrides)
    return ConsoleStoryUpdate(**data)


# ── Concurrency guard ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_version_bumps_on_save(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    story = await _make_story(writer, status=ConsoleStoryStatus.draft)
    assert story.version == 1

    body = _update_body(story, expected_version=1, standfirst="edited once")
    result = await console.update_story(story.id, body, current_user=writer)
    assert result.version == 2


@pytest.mark.asyncio
async def test_stale_save_rejected_with_409(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    story = await _make_story(writer, status=ConsoleStoryStatus.draft)

    # First save moves version 1 -> 2.
    await console.update_story(story.id, _update_body(story, expected_version=1), current_user=writer)

    # A second client still thinks it is on version 1 -> conflict.
    with pytest.raises(HTTPException) as exc:
        await console.update_story(story.id, _update_body(story, expected_version=1), current_user=writer)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_no_expected_version_skips_guard(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    story = await _make_story(writer, status=ConsoleStoryStatus.draft)
    # No expected_version -> guard is a no-op, save still succeeds and bumps.
    result = await console.update_story(story.id, _update_body(story), current_user=writer)
    assert result.version == 2


# ── changes_requested ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_editor_requests_changes_notifies_writer(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer, status=ConsoleStoryStatus.pending_review)

    body = ConsoleStoryStatusUpdate(
        status=ConsoleStoryStatus.changes_requested,
        editor_note="Tighten the lede.",
        expected_version=1,
    )
    result = await console.update_story_status(story.id, body, current_user=editor)
    assert result.status == ConsoleStoryStatus.changes_requested

    notif = await Notification.filter(recipient_id=writer.id).first()
    assert notif is not None
    assert notif.notif_type == NotificationType.story_changes_requested
    assert "Tighten the lede" in notif.body


@pytest.mark.asyncio
async def test_request_changes_note_mirrored_into_thread(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer, status=ConsoleStoryStatus.pending_review)

    body = ConsoleStoryStatusUpdate(
        status=ConsoleStoryStatus.changes_requested,
        editor_note="Add a source for paragraph 3.",
        expected_version=1,
    )
    await console.update_story_status(story.id, body, current_user=editor)

    comments = await StoryComment.filter(story_id=story.id).prefetch_related("author")
    assert len(comments) == 1
    assert comments[0].author_id == editor.id
    assert "Add a source" in comments[0].body


@pytest.mark.asyncio
async def test_request_changes_without_note_creates_no_comment(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer, status=ConsoleStoryStatus.pending_review)

    body = ConsoleStoryStatusUpdate(status=ConsoleStoryStatus.changes_requested, expected_version=1)
    await console.update_story_status(story.id, body, current_user=editor)
    assert await StoryComment.filter(story_id=story.id).count() == 0


@pytest.mark.asyncio
async def test_plain_editor_note_goes_to_thread_not_column(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer, status=ConsoleStoryStatus.draft)

    body = _update_body(story, expected_version=1, editor_note="Consider a stronger headline.")
    await console.update_story(story.id, body, current_user=editor)

    refreshed = await ConsoleStory.get(id=story.id)
    assert refreshed.editor_note is None  # legacy column no longer written

    comments = await StoryComment.filter(story_id=story.id)
    assert len(comments) == 1
    assert "stronger headline" in comments[0].body
    assert await Notification.filter(
        recipient_id=writer.id, notif_type=NotificationType.story_comment
    ).exists()


# ── #9: open comments reconciled with status ────────────────────────────────────

@pytest.mark.asyncio
async def test_resubmit_resolves_open_comments(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer, status=ConsoleStoryStatus.pending_review)

    await console.update_story_status(
        story.id,
        ConsoleStoryStatusUpdate(status=ConsoleStoryStatus.changes_requested, editor_note="fix the figure", expected_version=1),
        current_user=editor,
    )
    assert await StoryComment.filter(story_id=story.id, is_resolved=False).count() == 1

    # Writer resubmits for review (version bumped to 2 by the request-changes save).
    await console.update_story_status(
        story.id,
        ConsoleStoryStatusUpdate(status=ConsoleStoryStatus.pending_review, expected_version=2),
        current_user=writer,
    )
    assert await StoryComment.filter(story_id=story.id, is_resolved=False).count() == 0


@pytest.mark.asyncio
async def test_publish_resolves_open_comments(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer, status=ConsoleStoryStatus.pending_review)

    await console.create_story_comment(
        story.id, StoryCommentCreate(body="needs a source"), current_user=editor
    )
    assert await StoryComment.filter(story_id=story.id, is_resolved=False).count() == 1

    await console.update_story_status(
        story.id,
        ConsoleStoryStatusUpdate(status=ConsoleStoryStatus.publish, expected_version=1),
        current_user=editor,
    )
    assert await StoryComment.filter(story_id=story.id, is_resolved=False).count() == 0


@pytest.mark.asyncio
async def test_writer_cannot_request_changes(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    story = await _make_story(writer, status=ConsoleStoryStatus.draft)
    body = ConsoleStoryStatusUpdate(status=ConsoleStoryStatus.changes_requested, expected_version=1)
    with pytest.raises(HTTPException) as exc:
        await console.update_story_status(story.id, body, current_user=writer)
    assert exc.value.status_code == 403


# ── Notify-on-edit ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_editor_editing_writers_content_notifies_writer(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer, status=ConsoleStoryStatus.pending_review)

    body = _update_body(
        story,
        expected_version=1,
        sections=[SectionData(id="s1", type="text", content="EDITOR rewrote this")],
    )
    await console.update_story(story.id, body, current_user=editor)

    notif = await Notification.filter(
        recipient_id=writer.id, notif_type=NotificationType.story_edited
    ).first()
    assert notif is not None


@pytest.mark.asyncio
async def test_notify_on_edit_debounced_until_read(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer, status=ConsoleStoryStatus.pending_review)

    async def _edit(expected_version: int, text: str):
        body = _update_body(
            story,
            expected_version=expected_version,
            sections=[SectionData(id="s1", type="text", content=text)],
        )
        await console.update_story(story.id, body, current_user=editor)

    edited_q = Notification.filter(
        recipient_id=writer.id, notif_type=NotificationType.story_edited
    )

    await _edit(1, "edit one")
    assert await edited_q.count() == 1

    # Second edit in the same session — still only one unread ping.
    await _edit(2, "edit two")
    assert await edited_q.count() == 1

    # Writer reads it; a later edit notifies afresh.
    await Notification.filter(
        recipient_id=writer.id, notif_type=NotificationType.story_edited
    ).update(is_read=True)
    await _edit(3, "edit three")
    assert await edited_q.count() == 2


@pytest.mark.asyncio
async def test_editorial_team_fanout_role_filtered(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    admin = await _make_user(UserRole.admin, "Admin")
    reader = await _make_user(UserRole.reader, "Reader")
    inactive_editor = await _make_user(UserRole.editor, "Ghost", is_active=False)
    story = await _make_story(writer, status=ConsoleStoryStatus.draft)

    await console.update_story_status(
        story.id,
        ConsoleStoryStatusUpdate(status=ConsoleStoryStatus.pending_review, expected_version=1),
        current_user=writer,
    )

    assert await Notification.filter(recipient_id=editor.id, notif_type=NotificationType.story_submitted).count() == 1
    assert await Notification.filter(recipient_id=admin.id, notif_type=NotificationType.story_submitted).count() == 1
    # Readers and inactive editors are excluded.
    assert await Notification.filter(recipient_id=reader.id).count() == 0
    assert await Notification.filter(recipient_id=inactive_editor.id).count() == 0


@pytest.mark.asyncio
async def test_no_edit_notification_when_content_unchanged(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer, status=ConsoleStoryStatus.pending_review)

    # Editor saves without touching title/standfirst/sections.
    await console.update_story(story.id, _update_body(story, expected_version=1), current_user=editor)

    count = await Notification.filter(
        recipient_id=writer.id, notif_type=NotificationType.story_edited
    ).count()
    assert count == 0


# ── Threaded comments ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_editor_comment_notifies_writer(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer)

    result = await console.create_story_comment(
        story.id, StoryCommentCreate(body="Please add a source for paragraph 3."), current_user=editor
    )
    assert result.is_resolved is False
    assert result.author.id == str(editor.id)

    notif = await Notification.filter(
        recipient_id=writer.id, notif_type=NotificationType.story_comment
    ).first()
    assert notif is not None


@pytest.mark.asyncio
async def test_writer_comment_notifies_editorial_team(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer)

    await console.create_story_comment(
        story.id, StoryCommentCreate(body="Fixed — added the NBS link."), current_user=writer
    )
    notif = await Notification.filter(
        recipient_id=editor.id, notif_type=NotificationType.story_comment
    ).first()
    assert notif is not None


@pytest.mark.asyncio
async def test_resolve_and_list_comments(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer)

    created = await console.create_story_comment(
        story.id, StoryCommentCreate(body="needs work"), current_user=editor
    )
    resolved = await console.resolve_story_comment(
        story.id, uuid.UUID(created.id), StoryCommentResolve(is_resolved=True), current_user=writer
    )
    assert resolved.is_resolved is True
    assert resolved.resolved_by_id == str(writer.id)

    listed = await console.list_story_comments(story.id, skip=0, limit=50, current_user=writer)
    assert len(listed) == 1
    assert listed[0].is_resolved is True


@pytest.mark.asyncio
async def test_comments_pagination(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    editor = await _make_user(UserRole.editor, "Editor")
    story = await _make_story(writer)
    for i in range(3):
        await console.create_story_comment(
            story.id, StoryCommentCreate(body=f"comment {i}"), current_user=editor
        )
    page1 = await console.list_story_comments(story.id, skip=0, limit=2, current_user=writer)
    page2 = await console.list_story_comments(story.id, skip=2, limit=2, current_user=writer)
    assert len(page1) == 2
    assert len(page2) == 1
    # Chronological order preserved across pages.
    assert page1[0].body.endswith("0") and page2[0].body.endswith("2")


@pytest.mark.asyncio
async def test_outsider_cannot_read_thread(db):
    writer = await _make_user(UserRole.reporter, "Bukola")
    other = await _make_user(UserRole.reporter, "Stranger")
    story = await _make_story(writer)
    with pytest.raises(HTTPException) as exc:
        await console.list_story_comments(story.id, current_user=other)
    assert exc.value.status_code == 403
