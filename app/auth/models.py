import uuid

from tortoise import fields
from tortoise.models import Model

from app.core.roles import UserRole


class User(Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    email = fields.CharField(max_length=320, unique=True, index=True)
    hashed_password = fields.CharField(max_length=1024)
    is_active = fields.BooleanField(default=True)
    is_superuser = fields.BooleanField(default=False)
    is_verified = fields.BooleanField(default=False)
    role = fields.CharEnumField(UserRole, default=UserRole.reader, max_length=20)
    display_name = fields.CharField(max_length=100, null=True)
    # Stable public handle for author-page URLs (/author/<slug>). Decoupled from
    # display_name so a rename never breaks existing links. Generated once and
    # then fixed; see app.auth.slugs.ensure_user_slug.
    slug = fields.CharField(max_length=120, null=True, unique=True, index=True)
    avatar_url = fields.CharField(max_length=500, null=True)
    phone = fields.CharField(max_length=20, null=True)
    state = fields.CharField(max_length=100, null=True)
    is_diaspora = fields.BooleanField(default=False)
    bio = fields.TextField(null=True)
    linkedin_url = fields.CharField(max_length=300, null=True)
    twitter_url = fields.CharField(max_length=300, null=True)
    public_email = fields.CharField(max_length=320, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "users"

    def __str__(self) -> str:
        return f"<User {self.email} role={self.role}>"


class UserPreferences(Model):
    id = fields.IntField(pk=True)
    user: fields.OneToOneRelation[User] = fields.OneToOneField(
        "models.User", related_name="preferences", on_delete=fields.CASCADE
    )
    topics = fields.JSONField(default=list)
    city = fields.CharField(max_length=100, default="Lagos")
    notify_breaking = fields.BooleanField(default=True)
    notify_digest = fields.BooleanField(default=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "user_preferences"
