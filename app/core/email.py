"""
Email service — swap providers by setting EMAIL_PROVIDER in .env:
  EMAIL_PROVIDER=console  →  logs to stdout (default, zero config)
  EMAIL_PROVIDER=brevo    →  sends via Brevo transactional API
"""

import logging

logger = logging.getLogger(__name__)


class EmailClient:
    """Thin abstraction over the configured email provider."""

    async def send(self, to_email: str, to_name: str, subject: str, html_body: str) -> None:
        from app.config import settings

        if settings.EMAIL_PROVIDER == "brevo":
            await self._send_brevo(to_email, to_name, subject, html_body)
        else:
            self._log(to_email, subject, html_body)

    # ── Provider implementations ───────────────────────────────────────────

    def _log(self, to_email: str, subject: str, html_body: str) -> None:
        logger.info("[EMAIL:console] to=%s subject=%r", to_email, subject)
        logger.debug("[EMAIL:console] body=\n%s", html_body)

    async def _send_brevo(
        self, to_email: str, to_name: str, subject: str, html_body: str
    ) -> None:
        import httpx
        from app.config import settings

        payload = {
            "sender": {
                "name": settings.EMAIL_FROM_NAME,
                "email": settings.EMAIL_FROM_ADDRESS,
            },
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html_body,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers={
                    "accept": "application/json",
                    "api-key": settings.BREVO_API_KEY,
                    "content-type": "application/json",
                },
            )
            resp.raise_for_status()

    # ── Templated senders ─────────────────────────────────────────────────

    async def send_welcome_verify(
        self, to_email: str, to_name: str, verify_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Welcome to Prime Times Daily — please verify your email",
            html_body=_tpl_welcome_verify(to_name, verify_url),
        )

    async def send_verify_email(
        self, to_email: str, to_name: str, verify_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Verify your Prime Times Daily email address",
            html_body=_tpl_verify(to_name, verify_url),
        )

    async def send_password_reset(
        self, to_email: str, to_name: str, reset_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Reset your Prime Times Daily password",
            html_body=_tpl_reset(to_name, reset_url),
        )


# ── Email templates ────────────────────────────────────────────────────────
# Plain inline HTML — replace with a proper template engine (Jinja2, MJML, etc.)
# when you're ready to brand the emails properly.


def _tpl_welcome_verify(name: str, url: str) -> str:
    return f"""
<p>Hi {name},</p>
<p>Welcome to <strong>Prime Times Daily</strong>!</p>
<p>Please confirm your email address to activate your account:</p>
<p><a href="{url}">Verify email address</a></p>
<p>This link expires in 1 hour. If you did not register, ignore this email.</p>
"""


def _tpl_verify(name: str, url: str) -> str:
    return f"""
<p>Hi {name},</p>
<p>Please verify your <strong>Prime Times Daily</strong> email address:</p>
<p><a href="{url}">Verify email address</a></p>
<p>This link expires in 1 hour.</p>
"""


def _tpl_reset(name: str, url: str) -> str:
    return f"""
<p>Hi {name},</p>
<p>A password reset was requested for your <strong>Prime Times Daily</strong> account.</p>
<p><a href="{url}">Reset my password</a></p>
<p>This link expires in 1 hour. If you did not request this, ignore this email.</p>
"""


email_client = EmailClient()
