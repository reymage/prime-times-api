"""
Email service — swap providers by setting EMAIL_PROVIDER in .env:
  EMAIL_PROVIDER=console  →  logs to stdout (default, zero config)
  EMAIL_PROVIDER=brevo    →  sends via Brevo transactional API

Automated mail is sent from noreply@wire24news.com.
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
            subject="Welcome to Wire24 — please verify your email",
            html_body=_tpl_welcome_verify(to_name, verify_url),
        )

    async def send_verify_email(
        self, to_email: str, to_name: str, verify_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Verify your Wire24 email address",
            html_body=_tpl_verify(to_name, verify_url),
        )

    async def send_password_reset(
        self, to_email: str, to_name: str, reset_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Reset your Wire24 password",
            html_body=_tpl_reset(to_name, reset_url),
        )

    async def send_contact_message(
        self,
        to_email: str,
        reason_label: str,
        name: str,
        email: str,
        organisation: str | None,
        subject: str,
        message: str,
    ) -> None:
        await self.send(
            to_email,
            "Wire24 Team",
            subject=f"[Contact form] {reason_label} — {name}",
            html_body=_tpl_contact_message(
                reason_label, name, email, organisation, subject, message
            ),
        )

    # ── Contributor reward emails ──────────────────────────────────────────

    async def send_application_approved(
        self, to_email: str, to_name: str, kyc_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Your Wire24 contributor application is approved",
            html_body=_tpl_application_approved(to_name, kyc_url),
        )

    async def send_application_approved_new_account(
        self, to_email: str, to_name: str, login_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Your Wire24 contributor application is approved",
            html_body=_tpl_application_approved_new_account(to_name, to_email, login_url),
        )

    async def send_kyc_approved(
        self, to_email: str, to_name: str, console_url: str
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Identity verified — your contributor console is now open",
            html_body=_tpl_kyc_approved(to_name, console_url),
        )

    async def send_kyc_rejected(
        self, to_email: str, to_name: str, kyc_url: str, note: str | None
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Action required: identity verification could not be completed",
            html_body=_tpl_kyc_rejected(to_name, kyc_url, note),
        )

    async def send_application_rejected(
        self, to_email: str, to_name: str, note: str | None
    ) -> None:
        await self.send(
            to_email,
            to_name,
            subject="Update on your Wire24 contributor application",
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
# All emails share one branded shell (`_layout`); each template supplies only
# its own copy. Brand: Wire24 (#090a8b primary, #efce3f accent), a brand of
# Lightway Media. Swap _layout for a real template engine (Jinja2/MJML) later.

BRAND_PRIMARY = "#090a8b"
BRAND_ACCENT = "#efce3f"
LOGO_URL = "https://wire24news.com/wire24_logo.png"
SITE_URL = "https://wire24news.com"
SUPPORT_EMAIL = "contributors@wire24news.com"


def _layout(
    *,
    title: str,
    body_html: str,
    preheader: str,
    cta_label: str | None = None,
    cta_url: str | None = None,
    footer_note: str | None = None,
) -> str:
    """Render the branded Wire24 email shell around `body_html`.

    `body_html` is centred copy (use <p>…</p>). When `cta_label`/`cta_url` are
    given, a primary button plus a copy-paste fallback link are rendered.
    `footer_note` is the small grey line shown above the brand footer.
    """
    cta_block = ""
    if cta_label and cta_url:
        cta_block = f"""
                <tr>
                  <td align="center" style="padding-bottom:28px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td align="center" bgcolor="{BRAND_PRIMARY}" style="border-radius:6px;">
                          <a href="{cta_url}" target="_blank" style="display:inline-block; padding:14px 36px; font-family:Arial, Helvetica, sans-serif; font-size:15px; font-weight:bold; color:#ffffff; text-decoration:none; border-radius:6px;">
                            {cta_label}
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-bottom:28px;">
                    <span style="font-family:Arial, Helvetica, sans-serif; font-size:13px; line-height:20px; color:#888888;">
                      Or copy and paste this link into your browser:<br />
                      <a href="{cta_url}" style="color:{BRAND_PRIMARY}; text-decoration:underline; word-break:break-all;">{cta_url}</a>
                    </span>
                  </td>
                </tr>"""

    footer_note_block = ""
    if footer_note:
        footer_note_block = f"""
                <tr>
                  <td align="center" style="padding-bottom:4px;">
                    <span style="font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:18px; color:#999999;">
                      {footer_note}
                    </span>
                  </td>
                </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title} — Wire24</title>
</head>
<body style="margin:0; padding:0; background-color:#ffffff; font-family:Arial, Helvetica, sans-serif;">

  <!-- Preheader (hidden preview text) -->
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    {preheader}
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#ffffff;">
    <tr>
      <td align="center" style="padding:40px 20px;">

        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:480px; margin:0 auto;">

          <!-- Logo -->
          <tr>
            <td align="center" style="padding-bottom:32px;">
              <a href="{SITE_URL}" target="_blank" style="text-decoration:none; border:0;">
                <img src="{LOGO_URL}" alt="Wire24" width="140" style="display:block; border:0; outline:none; text-decoration:none; height:auto; max-width:140px;" />
              </a>
            </td>
          </tr>

          <!-- Content block -->
          <tr>
            <td style="padding:0;">

              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="center" style="padding-bottom:8px;">
                    <span style="font-family:Arial, Helvetica, sans-serif; font-size:20px; font-weight:bold; color:{BRAND_PRIMARY};">
                      {title}
                    </span>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding:0 16px 28px 16px; font-family:Arial, Helvetica, sans-serif; font-size:15px; line-height:22px; color:#333333;">
                    {body_html}
                  </td>
                </tr>
{cta_block}
                <!-- Accent divider -->
                <tr>
                  <td style="padding:0 0 24px 0;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td style="font-size:0; line-height:0; height:3px; background-color:{BRAND_ACCENT};">&nbsp;</td>
                      </tr>
                    </table>
                  </td>
                </tr>
{footer_note_block}
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" style="padding-top:32px;">
              <span style="font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:18px; color:#aaaaaa;">
                Wire24 · wire24news.com<br />
                A brand of Lightway Media
              </span>
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>"""


# ── Account / auth templates ────────────────────────────────────────────────

def _tpl_welcome_verify(name: str, url: str) -> str:
    return _layout(
        title=f"Welcome to Wire24, {name}",
        preheader="Welcome to Wire24 — confirm your email to activate your account.",
        body_html=(
            "<p style=\"margin:0;\">Thanks for joining Wire24. Confirm your email address "
            "below to activate your account and start reading.</p>"
        ),
        cta_label="Confirm email",
        cta_url=url,
        footer_note=(
            "This link expires in 1 hour. If you didn't create a Wire24 account, "
            "you can safely ignore this email."
        ),
    )


def _tpl_verify(name: str, url: str) -> str:
    return _layout(
        title="Confirm your email address",
        preheader="Confirm your email address for your Wire24 account.",
        body_html=(
            f"<p style=\"margin:0;\">Hi {name}, please confirm your email address for your "
            "Wire24 account by clicking the button below.</p>"
        ),
        cta_label="Confirm email",
        cta_url=url,
        footer_note=(
            "This link expires in 1 hour. If you didn't request this, "
            "you can safely ignore this email."
        ),
    )


def _tpl_reset(name: str, url: str) -> str:
    return _layout(
        title="Reset your password",
        preheader="Reset the password for your Wire24 account.",
        body_html=(
            f"<p style=\"margin:0;\">Hi {name}, a password reset was requested for your "
            "Wire24 account. Click the button below to choose a new password.</p>"
        ),
        cta_label="Reset my password",
        cta_url=url,
        footer_note=(
            "This link expires in 1 hour. If you didn't request this, "
            "you can safely ignore this email — your password won't change."
        ),
    )


def _tpl_contact_message(
    reason_label: str,
    name: str,
    email: str,
    organisation: str | None,
    subject: str,
    message: str,
) -> str:
    org_row = (
        f"<p style=\"margin:0 0 6px;\"><strong>Organisation:</strong> {organisation}</p>"
        if organisation
        else ""
    )
    subject_row = (
        f"<p style=\"margin:0 0 6px;\"><strong>Subject:</strong> {subject}</p>" if subject else ""
    )
    safe_message = message.replace("\n", "<br />")
    return _layout(
        title="New contact form message",
        preheader=f"{reason_label} — new message from {name} via the Wire24 contact page.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">A new message was submitted on the Wire24 "
            "contact page.</p>"
            f"<p style=\"margin:0 0 6px;\"><strong>Reason:</strong> {reason_label}</p>"
            f"<p style=\"margin:0 0 6px;\"><strong>Name:</strong> {name}</p>"
            f"<p style=\"margin:0 0 6px;\"><strong>Email:</strong> "
            f"<a href=\"mailto:{email}\" style=\"color:{BRAND_PRIMARY};\">{email}</a></p>"
            f"{org_row}"
            f"{subject_row}"
            f"<p style=\"margin:14px 0 0; text-align:left;\">{safe_message}</p>"
        ),
        footer_note="Reply directly to the sender's email address above.",
    )


# ── Contributor reward templates ────────────────────────────────────────────

def _tpl_application_approved(name: str, kyc_url: str) -> str:
    return _layout(
        title="Your application is approved",
        preheader="Your Wire24 contributor application is approved — complete your KYC.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, great news — your application to join the "
            "Wire24 contributor programme has been approved.</p>"
            "<p style=\"margin:0 0 14px;\">The next step is to complete your identity "
            "verification (KYC) so we can unlock your contributor console.</p>"
            "<p style=\"margin:0;\">It takes just a few minutes. You'll need a valid "
            "government-issued ID (National ID, International Passport, Driver's Licence, or "
            "Voter's Card) and your NIN or BVN.</p>"
        ),
        cta_label="Complete identity verification",
        cta_url=kyc_url,
        footer_note="Welcome to the team.",
    )


def _tpl_application_approved_new_account(name: str, email: str, login_url: str) -> str:
    return _layout(
        title="Your application is approved",
        preheader="Your Wire24 contributor application is approved — set up your account.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, great news — your application to join the "
            "Wire24 contributor programme has been approved.</p>"
            f"<p style=\"margin:0 0 14px;\">A contributor account has been created for you using "
            f"this email address (<strong>{email}</strong>). To finish onboarding:</p>"
            "<p style=\"margin:0 0 6px;\">1. Use the button below to open Wire24.</p>"
            f"<p style=\"margin:0 0 6px;\">2. Click <strong>Forgot password?</strong> and enter "
            f"<strong>{email}</strong> to set your password.</p>"
            "<p style=\"margin:0;\">3. Once logged in, complete your identity verification to "
            "unlock the contributor console.</p>"
        ),
        cta_label="Set up your account",
        cta_url=login_url,
        footer_note="Welcome to the team.",
    )


def _tpl_kyc_approved(name: str, console_url: str) -> str:
    return _layout(
        title="Identity verified",
        preheader="Your identity is verified — your Wire24 contributor console is open.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, your identity has been verified. You now "
            "have full access to the Wire24 contributor console.</p>"
            "<p style=\"margin:0;\">You can submit stories, track your earnings, and manage your "
            "payout details. Welcome aboard.</p>"
        ),
        cta_label="Go to your console",
        cta_url=console_url,
    )


def _tpl_kyc_rejected(name: str, kyc_url: str, note: str | None) -> str:
    note_block = (
        f"<p style=\"margin:0 0 14px;\"><strong>Reason:</strong> {note}</p>" if note else ""
    )
    return _layout(
        title="Verification could not be completed",
        preheader="Action required — we couldn't verify your identity on Wire24.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, we were unable to verify your identity "
            "using the documents you submitted to Wire24.</p>"
            f"{note_block}"
            "<p style=\"margin:0;\">Please resubmit your verification with a clear photo of a "
            "valid government-issued ID and make sure your NIN or BVN is correct.</p>"
        ),
        cta_label="Resubmit identity verification",
        cta_url=kyc_url,
        footer_note=(
            f"Questions? Contact us at <a href=\"mailto:{SUPPORT_EMAIL}\" "
            f"style=\"color:{BRAND_PRIMARY};\">{SUPPORT_EMAIL}</a>."
        ),
    )


def _tpl_application_rejected(name: str, note: str | None) -> str:
    note_block = (
        f"<p style=\"margin:0 0 14px;\"><em>Reviewer note: {note}</em></p>" if note else ""
    )
    return _layout(
        title="Update on your application",
        preheader="An update on your Wire24 contributor application.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, thank you for your interest in the Wire24 "
            "contributor programme.</p>"
            "<p style=\"margin:0 0 14px;\">After reviewing your application, we're unable to "
            "approve it at this time.</p>"
            f"{note_block}"
            "<p style=\"margin:0;\">You're welcome to apply again in the future.</p>"
        ),
        footer_note=(
            f"Questions? Contact our editorial team at <a href=\"mailto:{SUPPORT_EMAIL}\" "
            f"style=\"color:{BRAND_PRIMARY};\">{SUPPORT_EMAIL}</a>."
        ),
    )


def _tpl_earnings_distributed(
    name: str, week_start: str, week_end: str, amount: str, earnings_url: str
) -> str:
    return _layout(
        title="Your weekly earnings are pending review",
        preheader=f"Your Wire24 earnings for {week_start} – {week_end} are pending review.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, your earnings for the week of "
            f"<strong>{week_start} – {week_end}</strong> have been calculated and are now "
            "pending editorial review.</p>"
            f"<p style=\"margin:0 0 14px;\"><strong>Pending amount: ₦{amount}</strong></p>"
            "<p style=\"margin:0;\">Once reviewed and approved by the editorial team, you'll be "
            "able to request a payout from your console.</p>"
        ),
        cta_label="View your earnings",
        cta_url=earnings_url,
    )


def _tpl_earning_approved(name: str, amount: str, payout_url: str) -> str:
    return _layout(
        title="Your earning is approved",
        preheader=f"Your Wire24 earning of ₦{amount} is approved — request a payout.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, your earning of <strong>₦{amount}</strong> "
            "has been approved by the editorial team.</p>"
            "<p style=\"margin:0;\">If your total approved balance meets the minimum payout "
            "threshold (₦5,000), you can now request a payout.</p>"
        ),
        cta_label="Request a payout",
        cta_url=payout_url,
    )


def _tpl_payout_approved(name: str, amount: str) -> str:
    return _layout(
        title="Your payout is approved",
        preheader=f"Your Wire24 payout of ₦{amount} has been approved.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, your payout request of "
            f"<strong>₦{amount}</strong> has been approved and is being processed.</p>"
            "<p style=\"margin:0;\">The transfer will be initiated shortly. We'll send a "
            "confirmation once the funds have been sent to your bank account.</p>"
        ),
    )


def _tpl_payout_paid(name: str, amount: str, bank_name: str, account_masked: str) -> str:
    return _layout(
        title="Your payout has been sent",
        preheader=f"₦{amount} has been sent to your bank account.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, <strong>₦{amount}</strong> has been sent "
            "to your bank account.</p>"
            f"<p style=\"margin:0 0 14px;\">Bank: {bank_name}<br>Account: {account_masked}</p>"
            "<p style=\"margin:0;\">Transfers typically arrive within minutes. If you don't "
            "receive the funds within 24 hours, please contact our support team.</p>"
        ),
        footer_note=(
            f"Need help? Contact us at <a href=\"mailto:{SUPPORT_EMAIL}\" "
            f"style=\"color:{BRAND_PRIMARY};\">{SUPPORT_EMAIL}</a>."
        ),
    )


def _tpl_payout_failed(name: str, amount: str, reason: str | None) -> str:
    reason_block = (
        f"<p style=\"margin:0 0 14px;\"><em>Reason: {reason}</em></p>" if reason else ""
    )
    return _layout(
        title="Your payout could not be completed",
        preheader=f"Action required — your Wire24 payout of ₦{amount} could not be completed.",
        body_html=(
            f"<p style=\"margin:0 0 14px;\">Hi {name}, unfortunately your payout transfer of "
            f"<strong>₦{amount}</strong> could not be completed.</p>"
            f"{reason_block}"
            "<p style=\"margin:0;\">Please verify your bank account details in the console and "
            "contact our support team so we can retry the transfer.</p>"
        ),
        footer_note=(
            f"Need help? Contact us at <a href=\"mailto:{SUPPORT_EMAIL}\" "
            f"style=\"color:{BRAND_PRIMARY};\">{SUPPORT_EMAIL}</a>."
        ),
    )


email_client = EmailClient()
