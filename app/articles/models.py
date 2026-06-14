import uuid

from tortoise import fields
from tortoise.models import Model


class Article(Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    slug = fields.CharField(max_length=200, unique=True, index=True)
    title = fields.CharField(max_length=500)
    excerpt = fields.TextField(default="")
    key_points = fields.JSONField(default=list, null=True)
    content = fields.TextField(default="")
    category = fields.CharField(max_length=100, index=True)
    image_url = fields.CharField(max_length=500, default="")
    author = fields.CharField(max_length=200, default="")
    # Stable link to the byline author (the writer). The `author`/`author_avatar`
    # strings above are a denormalized display cache kept in sync from this user;
    # `author_slug` powers the author-page link without a join. Null for external
    # imports that have no internal user.
    author_id = fields.UUIDField(null=True, index=True)
    author_slug = fields.CharField(max_length=120, null=True, index=True)
    source = fields.CharField(max_length=200, default="")
    source_icon = fields.CharField(max_length=500, null=True)
    source_url = fields.CharField(max_length=500, null=True)
    is_video = fields.BooleanField(default=False)
    video_url = fields.CharField(max_length=500, null=True)
    is_internal = fields.BooleanField(default=False)
    is_featured = fields.BooleanField(default=False)
    is_premium = fields.BooleanField(default=False)
    is_editorial_pick = fields.BooleanField(default=False)
    author_avatar = fields.CharField(max_length=500, null=True)
    # Raw read count (every load) — powers trending/popularity.
    view_count = fields.IntField(default=0)
    # Unique readers (distinct device ids) — "how many people viewed this".
    unique_view_count = fields.IntField(default=0)
    # Number of successful shares (native share completed, link copied, or a
    # share-platform window opened).
    share_count = fields.IntField(default=0)
    # Reader feedback — "Did this story help you understand the issue?"
    # Unique per device: one vote per reader (switchable yes<->no).
    helpful_yes = fields.IntField(default=0)
    helpful_no = fields.IntField(default=0)
    # FK back to the ConsoleStory that originated this article (null for external imports).
    console_story_id = fields.UUIDField(null=True, index=True)
    published_at = fields.DatetimeField()
    created_at = fields.DatetimeField(auto_now_add=True)
    tags = fields.JSONField(default=list)
    issue_cluster = fields.ForeignKeyField(
        "models.IssueCluster", related_name="articles", null=True
    )

    class Meta:
        table = "articles"
        ordering = ["-published_at"]


class SavedArticle(Model):
    id = fields.IntField(pk=True)
    user: fields.ForeignKeyRelation = fields.ForeignKeyField(
        "models.User", related_name="saved_articles", on_delete=fields.CASCADE
    )
    article: fields.ForeignKeyRelation[Article] = fields.ForeignKeyField(
        "models.Article", related_name="saves", on_delete=fields.CASCADE
    )
    saved_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "saved_articles"
        unique_together = (("user_id", "article_id"),)


class ArticleView(Model):
    """One row per (article, device) — used to dedupe unique views.

    device_id is a client-generated id (no login required); it falls back to a
    hash of IP+User-Agent when the client doesn't supply one.
    """
    id = fields.IntField(pk=True)
    article_id = fields.UUIDField(index=True)
    device_id = fields.CharField(max_length=64)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "article_views"
        unique_together = (("article_id", "device_id"),)


class ArticleFeedback(Model):
    """One vote per (article, device) — 'Did this story help you understand?'.

    Switchable: a device can change yes<->no, but only ever counts once.
    """
    id = fields.IntField(pk=True)
    article_id = fields.UUIDField(index=True)
    device_id = fields.CharField(max_length=64)
    helpful = fields.BooleanField()
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "article_feedback"
        unique_together = (("article_id", "device_id"),)
