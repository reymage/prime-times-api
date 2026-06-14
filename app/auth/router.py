"""
Auth router — mounts all authentication and user-management endpoints.

Public surface:
  POST  /api/auth/login                — get JWT (OAuth2 form)
  POST  /api/auth/logout               — revoke token (no-op for stateless JWT)
  POST  /api/auth/register             — create reader account
  POST  /api/auth/forgot-password      — request password-reset email
  POST  /api/auth/reset-password       — submit new password via reset token
  POST  /api/auth/request-verify       — resend verification email
  POST  /api/auth/verify               — verify email with token

  GET   /api/users/me                  — get own profile
  PATCH /api/users/me                  — update own profile (display_name, password, email)

Admin surface (role >= admin required):
  GET   /api/admin/users               — paginated user list
  GET   /api/admin/users/{id}          — single user detail
  PATCH /api/admin/users/{id}/role     — change a user's role
  PATCH /api/admin/users/{id}/status   — activate / deactivate a user

Super-admin only:
  DELETE /api/admin/users/{id}         — hard-delete a user
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.auth.backends import auth_backend
from app.auth.dependencies import (
    current_active_user,
    fastapi_users,
    get_user_manager,
)
from app.auth.manager import UserManager
from app.auth.models import User
from app.auth.models import UserPreferences
from app.auth.schemas import (
    UserAdminRead,
    UserCreate,
    UserPreferencesRead,
    UserPreferencesUpdate,
    UserRead,
    UserRoleUpdate,
    UserStatusUpdate,
    UserUpdate,
)
from app.core.roles import UserRole, role_has_at_least
from app.storage import ALLOWED_MIME_TYPES, MAX_UPLOAD_BYTES, is_r2_configured, upload_to_r2

router = APIRouter(prefix="/api")

# ── fastapi-users built-in routers ────────────────────────────────────────

router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)

# ── User preferences ──────────────────────────────────────────────────────


@router.get("/users/me/preferences", response_model=UserPreferencesRead, tags=["users"])
async def get_my_preferences(
    current_user: User = Depends(current_active_user),
) -> UserPreferences:
    prefs, _ = await UserPreferences.get_or_create(user_id=current_user.id)
    return prefs


@router.patch("/users/me/preferences", response_model=UserPreferencesRead, tags=["users"])
async def update_my_preferences(
    body: UserPreferencesUpdate,
    current_user: User = Depends(current_active_user),
) -> UserPreferences:
    prefs, _ = await UserPreferences.get_or_create(user_id=current_user.id)
    data = body.model_dump(exclude_unset=True)
    if data:
        await prefs.update_from_dict(data).save()
    return prefs


# ── Avatar upload ─────────────────────────────────────────────────────────


@router.post("/users/me/avatar", tags=["users"])
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(current_active_user),
) -> dict:
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image format. Use JPEG, PNG, or WebP.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (max 10 MB).")
    if not is_r2_configured():
        raise HTTPException(status_code=503, detail="Storage not configured on this server.")
    url = await upload_to_r2(data, file.content_type, folder="avatars")
    current_user.avatar_url = url
    await current_user.save(update_fields=["avatar_url"])
    # Keep published bylines' avatars fresh.
    try:
        from app.auth.slugs import refresh_author_cache
        await refresh_author_cache(current_user)
    except Exception:
        pass
    return {"avatar_url": url}


# ── Admin: user management ────────────────────────────────────────────────


def _require_admin(current_user: User = Depends(current_active_user)) -> User:
    if not role_has_at_least(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Requires admin role or above")
    return current_user


def _require_super_admin(current_user: User = Depends(current_active_user)) -> User:
    if current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Requires super_admin role")
    return current_user


async def _get_target_user(user_id: uuid.UUID, user_manager: UserManager) -> User:
    try:
        return await user_manager.get(user_id)
    except Exception:
        raise HTTPException(status_code=404, detail="User not found")


@router.get("/admin/users", response_model=list[UserAdminRead], tags=["admin"])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _admin: User = Depends(_require_admin),
) -> list[User]:
    return await User.all().offset(skip).limit(limit).order_by("created_at")


@router.get("/admin/users/{user_id}", response_model=UserAdminRead, tags=["admin"])
async def get_user(
    user_id: uuid.UUID,
    user_manager: UserManager = Depends(get_user_manager),
    _admin: User = Depends(_require_admin),
) -> User:
    return await _get_target_user(user_id, user_manager)


@router.patch("/admin/users/{user_id}/role", response_model=UserAdminRead, tags=["admin"])
async def update_user_role(
    user_id: uuid.UUID,
    body: UserRoleUpdate,
    user_manager: UserManager = Depends(get_user_manager),
    current_user: User = Depends(_require_admin),
) -> User:
    target = await _get_target_user(user_id, user_manager)

    # Cannot modify yourself via this endpoint
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Use /users/me to update your own profile")

    # Only super_admin can touch admin-level or above accounts
    if role_has_at_least(target.role, UserRole.admin) and current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Only super_admin can modify admin-level users")

    # Cannot assign a role equal to or higher than your own (unless super_admin)
    if (
        current_user.role != UserRole.super_admin
        and role_has_at_least(body.role, current_user.role)
    ):
        raise HTTPException(
            status_code=403,
            detail="Cannot assign a role equal to or higher than your own",
        )

    await user_manager.user_db.update(target, {"role": body.role})
    return target


@router.patch("/admin/users/{user_id}/status", response_model=UserAdminRead, tags=["admin"])
async def update_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdate,
    user_manager: UserManager = Depends(get_user_manager),
    current_user: User = Depends(_require_admin),
) -> User:
    target = await _get_target_user(user_id, user_manager)

    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    if role_has_at_least(target.role, UserRole.admin) and current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Only super_admin can modify admin-level users")

    await user_manager.user_db.update(target, {"is_active": body.is_active})
    return target


@router.delete("/admin/users/{user_id}", status_code=204, tags=["admin"])
async def delete_user(
    user_id: uuid.UUID,
    user_manager: UserManager = Depends(get_user_manager),
    current_user: User = Depends(_require_super_admin),
) -> None:
    target = await _get_target_user(user_id, user_manager)

    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    await user_manager.delete(target)
