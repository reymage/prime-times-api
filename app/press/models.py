import uuid

from tortoise import fields
from tortoise.models import Model


class PressRelease(Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    slug = fields.CharField(max_length=220, unique=True, index=True)
    title = fields.CharField(max_length=500)
    # Short dek shown on the press-center stream and in social shares.
    excerpt = fields.TextField(default="")
    # Full body — plain paragraphs separated by blank lines.
    content = fields.TextField(default="")
    category = fields.CharField(max_length=100, default="Announcement", index=True)
    image_url = fields.CharField(max_length=500, default="")
    is_featured = fields.BooleanField(default=False)
    is_published = fields.BooleanField(default=True)
    published_at = fields.DatetimeField()
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "press_releases"
        ordering = ["-published_at"]
