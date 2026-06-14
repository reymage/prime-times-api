import enum
import uuid

from tortoise import fields
from tortoise.models import Model


class ConsoleStoryStatus(str, enum.Enum):
    publish = "publish"
    draft = "draft"
    pending_review = "pending_review"
    # Editor kicked the story back to the writer to fix something. Distinct from
    # 'draft' (a fresh draft the writer hasn't submitted) so the UI can tell them
    # apart and surface the editorial note prominently.
    changes_requested = "changes_requested"
    future = "future"
    auto_draft = "auto_draft"
    trash = "trash"
    revision = "revision"


class IssueClusterStatus(str, enum.Enum):
    active = "active"
    breaking = "breaking"
    archived = "archived"


class IssueCluster(Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    name = fields.CharField(max_length=200)
    slug = fields.CharField(max_length=220, unique=True)
    description = fields.TextField(default="")
    category = fields.CharField(max_length=100, default="")
    status = fields.CharEnumField(IssueClusterStatus, default=IssueClusterStatus.active, max_length=20)
    breaking_order = fields.IntField(null=True)
    cover_image = fields.CharField(max_length=500, null=True)
    created_by = fields.ForeignKeyField("models.User", related_name="created_issue_clusters")
    assigned_editor = fields.ForeignKeyField(
        "models.User", related_name="managed_issue_clusters", null=True
    )
    breaking_expires_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "issue_clusters"
        ordering = ["-updated_at"]


class ConsoleStory(Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    # The record creator. The public byline, however, is the *byline author* —
    # `assigned_to` if an editor commissioned the story to a writer, otherwise
    # `author` (see _byline_user_id in the console router).
    author = fields.ForeignKeyField("models.User", related_name="console_stories")
    # Set when an editor initiates a story and assigns it to a writer to write.
    # The assignee becomes the byline author and can see/edit the story.
    assigned_to = fields.ForeignKeyField(
        "models.User", related_name="assigned_stories", null=True, on_delete=fields.SET_NULL
    )
    # Internal audit only (never shown to readers): who last edited the content
    # and when. Lets the desk see editorial involvement without changing byline.
    last_edited_by = fields.ForeignKeyField(
        "models.User", related_name="edited_stories", null=True, on_delete=fields.SET_NULL
    )
    last_edited_at = fields.DatetimeField(null=True)
    title = fields.CharField(max_length=500, default="")
    standfirst = fields.TextField(default="")
    # JSON array of section objects: [{id, type, heading, content, ...}]
    sections = fields.JSONField(default=list)
    cover_image = fields.CharField(max_length=500, null=True)
    category = fields.CharField(max_length=100, default="")
    tags = fields.JSONField(default=list)
    story_type = fields.CharField(max_length=50, default="article")
    status = fields.CharEnumField(
        ConsoleStoryStatus,
        default=ConsoleStoryStatus.auto_draft,
        max_length=20,
    )
    scheduled_for = fields.DatetimeField(null=True)
    word_count = fields.IntField(default=0)
    # LEGACY: editorial notes now live in the StoryComment thread (the canonical
    # home). No longer written by the app; retained only so historical rows keep
    # their note. Do not add new writes here — use _post_editorial_note().
    editor_note = fields.TextField(null=True)
    # Geographic focus — writer indicates which regions the story targets
    geo_regions = fields.JSONField(default=list)
    # Featured flag — editors promote a story to the featured placement slot
    is_featured = fields.BooleanField(default=False)
    # Editorial pick — editors curate this story for the Editorial Picks section
    is_editorial_pick = fields.BooleanField(default=False)
    # When status=revision, points to the story this is a snapshot of
    revision_of = fields.ForeignKeyField(
        "models.ConsoleStory", related_name="revisions", null=True
    )
    # Issue cluster this story belongs to (optional)
    issue_cluster = fields.ForeignKeyField(
        "models.IssueCluster", related_name="stories", null=True
    )
    # ── Reward / pay-worthy fields ────────────────────────────────────────────
    # Set to True by editor when story passes: original reporting + local impact
    # + public interest. Only pay-worthy stories go behind paywall and qualify
    # for contributor rewards.
    is_pay_worthy = fields.BooleanField(default=False)
    # {original_reporting: bool, local_impact: bool, public_interest: bool}
    pay_worthy_rubric = fields.JSONField(null=True)
    # Incremented each time a reader unlocks this story via the paywall.
    paywall_read_count = fields.IntField(default=0)
    # 0-100 editorial quality score; used in the eligibility algorithm gate.
    editorial_score = fields.IntField(null=True)
    # Set when status transitions to 'publish'; used for tenure calculations.
    published_at = fields.DatetimeField(null=True)
    # Optimistic-lock counter. Bumped on every content/status save so a writer
    # and an editor editing concurrently can't silently clobber each other —
    # a stale save (expected_version != version) is rejected with 409.
    version = fields.IntField(default=1)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "console_stories"
        ordering = ["-updated_at"]


class StoryComment(Model):
    """An editorial back-and-forth note on a story.

    Replaces the single overwritable ``ConsoleStory.editor_note`` with a proper
    thread: editors and the writer can leave multiple comments, each one
    independently resolvable. ``editor_note`` is kept for backwards-compat but
    new conversations live here.
    """
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    story = fields.ForeignKeyField(
        "models.ConsoleStory", related_name="comments", on_delete=fields.CASCADE
    )
    author = fields.ForeignKeyField("models.User", related_name="story_comments")
    body = fields.TextField()
    # True once the writer (or an editor) marks the point addressed.
    is_resolved = fields.BooleanField(default=False)
    resolved_by = fields.ForeignKeyField(
        "models.User", related_name="resolved_story_comments", null=True
    )
    resolved_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "story_comments"
        ordering = ["created_at"]
