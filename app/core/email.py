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

    # ── Contributor reward emails ──────────────────────────────────────────

    async def send_application_approved(
        self, to_email: str, to_name: str, console_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Your Prime Times Daily contributor application is approved",
            html_body=_tpl_application_approved(to_name, console_url),
        )

    async def send_application_rejected(
        self, to_email: str, to_name: str, note: str | None
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Update on your Prime Times Daily contributor application",
            html_body=_tpl_application_rejected(to_name, note),
        )

    async def send_earnings_distributed(
        self,
        to_email: str,
        to_name: str,
        week_start: str,
        week_end: str,
        amount: str,
        earnings_url: str,
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject=f"Your earnings for {week_start} – {week_end} are pending review",
            html_body=_tpl_earnings_distributed(to_name, week_start, week_end, amount, earnings_url),
        )

    async def send_earning_approved(
        self, to_email: str, to_name: str, amount: str, payout_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject=f"₦{amount} earning approved — you can request a payout",
            html_body=_tpl_earning_approved(to_name, amount, payout_url),
        )

    async def send_payout_approved(
        self, to_email: str, to_name: str, amount: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject=f"Your payout of ₦{amount} has been approved",
            html_body=_tpl_payout_approved(to_name, amount),
        )

    async def send_payout_paid(
        self,
        to_email: str,
        to_name: str,
        amount: str,
        bank_name: str,
        account_number_masked: str,
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject=f"₦{amount} has been sent to your account",
            html_body=_tpl_payout_paid(to_name, amount, bank_name, account_number_masked),
        )

    async def send_payout_failed(
        self, to_email: str, to_name: str, amount: str, reason: str | None
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Your payout transfer could not be completed",
            html_body=_tpl_payout_failed(to_name, amount, reason),
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


# ── Contributor reward templates ───────────────────────────────────────────────

def _tpl_application_approved(name: str, console_url: str) -> str:
    return f"""
<p>Hi {name},</p>
<p>Great news — your application to join the <strong>Prime Times Daily</strong> contributor programme has been approved.</p>
<p>You now have access to the contributor console where you can submit stories, track your earnings, and manage your payout details.</p>
<p><a href="{console_url}">Go to your console</a></p>
<p>Welcome to the team.</p>
"""


def _tpl_application_rejected(name: str, note: str | None) -> str:
    note_block = f"<p><em>Reviewer note: {note}</em></p>" if note else ""
    return f"""
<p>Hi {name},</p>
<p>Thank you for your interest in the <strong>Prime Times Daily</strong> contributor programme.</p>
<p>After reviewing your application, we are unable to approve it at this time.</p>
{note_block}
<p>You are welcome to apply again in the future. If you have questions, please reach out to our editorial team.</p>
"""


def _tpl_earnings_distributed(
    name: str, week_start: str, week_end: str, amount: str, earnings_url: str
) -> str:
    return f"""
<p>Hi {name},</p>
<p>Your earnings for the week of <strong>{week_start} – {week_end}</strong> have been calculated and are now pending editorial review.</p>
<p><strong>Pending amount: ₦{amount}</strong></p>
<p>Once reviewed and approved by the editorial team, you will be able to request a payout from your console.</p>
<p><a href="{earnings_url}">View your earnings</a></p>
"""


def _tpl_earning_approved(name: str, amount: str, payout_url: str) -> str:
    return f"""
<p>Hi {name},</p>
<p>Your earning of <strong>₦{amount}</strong> has been approved by the editorial team.</p>
<p>If your total approved balance meets the minimum payout threshold (₦5,000), you can now request a payout.</p>
<p><a href="{payout_url}">Request a payout</a></p>
"""


def _tpl_payout_approved(name: str, amount: str) -> str:
    return f"""
<p>Hi {name},</p>
<p>Your payout request of <strong>₦{amount}</strong> has been approved and is being processed.</p>
<p>The transfer will be initiated shortly. You will receive a confirmation once the funds have been sent to your bank account.</p>
"""


def _tpl_payout_paid(name: str, amount: str, bank_name: str, account_masked: str) -> str:
    return f"""
<p>Hi {name},</p>
<p><strong>₦{amount}</strong> has been sent to your bank account.</p>
<p>Bank: {bank_name}<br>Account: {account_masked}</p>
<p>Transfers typically arrive within minutes. If you do not receive the funds within 24 hours, please contact our support team.</p>
"""


def _tpl_payout_failed(name: str, amount: str, reason: str | None) -> str:
    reason_block = f"<p><em>Reason: {reason}</em></p>" if reason else ""
    return f"""
<p>Hi {name},</p>
<p>Unfortunately, your payout transfer of <strong>₦{amount}</strong> could not be completed.</p>
{reason_block}
<p>Please verify your bank account details in the console and contact our support team so we can retry the transfer.</p>
"""


email_client = EmailClient()
