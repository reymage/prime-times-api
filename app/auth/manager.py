import logging
import uuid

from fastapi import Request
from fastapi_users import BaseUserManager, InvalidPasswordException, UUIDIDMixin

from app.auth.models import User
from app.core.email import email_client

logger = logging.getLogger(__name__)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    @property
    def reset_password_token_secret(self) -> str:  # type: ignore[override]
        from app.config import settings
        return settings.SECRET_KEY

    @property
    def verification_token_secret(self) -> str:  # type: ignore[override]
        from app.config import settings
        return settings.SECRET_KEY

    # ── Password validation ────────────────────────────────────────────────

    async def validate_password(self, password: str, user) -> None:
        if len(password) < 8:
            raise InvalidPasswordException(reason="Password must be at least 8 characters")

    # ── Lifecycle hooks ────────────────────────────────────────────────────

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        logger.info("User registered: %s", user.email)
        # Immediately trigger verification so the welcome+verify email goes out
        try:
            await self.request_verify(user, request)
        except Exception:
            logger.exception("Failed to send verification email to %s", user.email)

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        from app.config import settings

        logger.info("Verification requested for: %s", user.email)
        verify_url = f"{settings.FRONTEND_URL}/auth/verify-email?token={token}"
        name = user.display_name or user.email
        # First-time verification uses the combined welcome+verify template;
        # subsequent re-requests use the plain verify template.
        if not user.is_verified:
            await email_client.send_welcome_verify(user.email, name, verify_url)
        else:
            await email_client.send_verify_email(user.email, name, verify_url)

    async def on_after_verify(self, user: User, request: Request | None = None) -> None:
        logger.info("User verified: %s", user.email)

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        from app.config import settings

        logger.info("Password reset requested for: %s", user.email)
        reset_url = f"{settings.FRONTEND_URL}/auth/reset-password?token={token}"
        name = user.display_name or user.email
        await email_client.send_password_reset(user.email, name, reset_url)

    async def on_after_reset_password(
        self, user: User, request: Request | None = None
    ) -> None:
        logger.info("Password reset completed for: %s", user.email)

    async def on_after_login(
        self,
        user: User,
        request: Request | None = None,
        response=None,
    ) -> None:
        logger.debug("User logged in: %s", user.email)
