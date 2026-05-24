import uuid
from datetime import datetime

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict

from app.core.roles import UserRole


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Returned on every endpoint that exposes user data."""

    role: UserRole
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    state: str | None = None
    is_diaspora: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserCreate(schemas.BaseUserCreate):
    """Accepted body for POST /auth/register (public)."""

    display_name: str | None = None
    # role is intentionally absent — public registration always yields `reader`


class UserUpdate(schemas.BaseUserUpdate):
    """
    Accepted body for PATCH /users/me (safe — cannot change role, is_superuser, etc.).
    Users can update: password, email, display_name, and profile fields.
    """

    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    state: str | None = None
    is_diaspora: bool | None = None


# ── Admin-only schemas ────────────────────────────────────────────────────


class UserRoleUpdate(BaseModel):
    """Body for PATCH /admin/users/{id}/role."""

    role: UserRole


class UserStatusUpdate(BaseModel):
    """Body for PATCH /admin/users/{id}/status."""

    is_active: bool


class UserAdminRead(UserRead):
    """Extended read schema for admin-level views — includes internal flags."""

    is_active: bool
    is_superuser: bool
    is_verified: bool
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Preferences schemas ───────────────────────────────────────────────────────


class UserPreferencesRead(BaseModel):
    topics: list[str] = []
    city: str = "Lagos"
    notify_breaking: bool = True
    notify_digest: bool = True

    model_config = ConfigDict(from_attributes=True)


class UserPreferencesUpdate(BaseModel):
    topics: list[str] | None = None
    city: str | None = None
    notify_breaking: bool | None = None
    notify_digest: bool | None = None
