import enum

from fastapi import Depends, HTTPException


class UserRole(str, enum.Enum):
    reader = "reader"
    contributor = "contributor"
    reporter = "reporter"
    editor = "editor"
    admin = "admin"
    super_admin = "super_admin"


_ROLE_ORDER: list[UserRole] = [
    UserRole.reader,
    UserRole.contributor,
    UserRole.reporter,
    UserRole.editor,
    UserRole.admin,
    UserRole.super_admin,
]


def role_level(role: UserRole) -> int:
    return _ROLE_ORDER.index(role)


def role_has_at_least(role: UserRole, minimum: UserRole) -> bool:
    return role_level(role) >= role_level(minimum)


def require_role(minimum: UserRole):
    """
    Returns a FastAPI dependency that rejects users whose role is below `minimum`.
    Import and use like: `user: User = Depends(require_role(UserRole.editor))`
    """
    from app.auth.dependencies import current_active_user
    from app.auth.models import User

    def _check(current_user: User = Depends(current_active_user)) -> User:
        if not role_has_at_least(current_user.role, minimum):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return _check
