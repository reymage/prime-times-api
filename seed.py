"""
Seed script — creates or updates specific users and their roles.

Usage (from the api/ directory):
    python seed.py

Requires a valid .env file with DATABASE_URL and SECRET_KEY.
"""
import asyncio
import sys
import os

# Allow importing app modules from the api/ directory
sys.path.insert(0, os.path.dirname(__file__))

from tortoise import Tortoise
from app.database import TORTOISE_ORM
from app.auth.models import User
from app.core.roles import UserRole
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

DEFAULT_PASSWORD = "PTD@2024!"

SEED_USERS = [
    ("neithmostafa@gmail.com",   UserRole.reader,      "Neith Mostafa"),
    ("reymageltd@gmail.com",     UserRole.super_admin, "Reymage Ltd"),
    ("primetimesdaily@gmail.com", UserRole.editor,     "Prime Times Daily"),
    ("imcmnigeria@gmail.com",    UserRole.editor,      "IMCM Nigeria"),
]


async def main() -> None:
    await Tortoise.init(config=TORTOISE_ORM)

    ph = PasswordHash([BcryptHasher()])

    for email, role, display_name in SEED_USERS:
        existing = await User.filter(email=email).first()
        if existing:
            existing.role = role
            if role == UserRole.super_admin:
                existing.is_superuser = True
            await existing.save()
            print(f"[UPDATED]  {email}  →  {role.value}")
        else:
            hashed = ph.hash(DEFAULT_PASSWORD)
            await User.create(
                email=email,
                hashed_password=hashed,
                role=role,
                display_name=display_name,
                is_active=True,
                is_verified=True,
                is_superuser=(role == UserRole.super_admin),
            )
            print(f"[CREATED]  {email}  role={role.value}  (default password: {DEFAULT_PASSWORD})")

    await Tortoise.close_connections()
    print("\nSeeding complete.")


if __name__ == "__main__":
    asyncio.run(main())
