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
    source = fields.CharField(max_length=200, default="")
    source_icon = fields.CharField(max_length=500, null=True)
    source_url = fields.CharField(max_length=500, null=True)
    is_video = fields.BooleanField(default=False)
    video_url = fields.CharField(max_length=500, null=True)
    is_internal = fields.BooleanField(default=False)
    is_featured = fields.BooleanField(default=False)
    is_premium = fields.BooleanField(default=False)
    author_avatar = fields.CharField(max_length=500, null=True)
    view_count = fields.IntField(default=0)
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
