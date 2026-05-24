import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi_users import FastAPIUsers

from app.auth.backends import auth_backend
from app.auth.database import TortoiseUserDatabase
from app.auth.manager import UserManager
from app.auth.models import User


async def get_user_db() -> AsyncGenerator[TortoiseUserDatabase, None]:
    yield TortoiseUserDatabase()


async def get_user_manager(
    user_db: TortoiseUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


# ── fastapi-users facade ──────────────────────────────────────────────────
fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

# Reusable current-user dependencies
current_active_user = fastapi_users.current_user(active=True)
current_verified_user = fastapi_users.current_user(active=True, verified=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
