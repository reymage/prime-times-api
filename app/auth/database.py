import uuid
from typing import Any

from fastapi_users.db import BaseUserDatabase

from app.auth.models import User


class TortoiseUserDatabase(BaseUserDatabase[User, uuid.UUID]):
    """
    Minimal Tortoise ORM adapter for fastapi-users.
    No OAuth support — add add_oauth_account / update_oauth_account if needed later.
    """

    async def get(self, id: uuid.UUID) -> User | None:
        return await User.filter(id=id).first()

    async def get_by_email(self, email: str) -> User | None:
        return await User.filter(email=email.lower()).first()

    async def create(self, create_dict: dict[str, Any]) -> User:
        if "email" in create_dict:
            create_dict["email"] = create_dict["email"].lower()
        return await User.create(**create_dict)

    async def update(self, user: User, update_dict: dict[str, Any]) -> User:
        if "email" in update_dict:
            update_dict["email"] = update_dict["email"].lower()
        await user.update_from_dict(update_dict).save()
        return user

    async def delete(self, user: User) -> None:
        await user.delete()
