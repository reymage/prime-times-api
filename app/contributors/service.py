"""
Contributor reward service — all business logic lives here.

Key rules enforced:
  1. reward_start_date gate: nothing runs before that date.
  2. 90-day vesting from first_published_story_date.
  3. Algorithm criteria: tenure ≥3mo, ≥3 stories/week avg, ≥60% pay-worthy
     in last 30 days, editorial_score avg ≥70 for last 2 months.
  4. Editorial override can bypass or block algorithm result.
  5. Revenue pool = paywall income only. Distribution is pro-rata by
     paywall_read_count of pay-worthy stories published in the period.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from tortoise.exceptions import DoesNotExist

from app.console.models import ConsoleStory, ConsoleStoryStatus
from app.contributors.models import (
    ApplicationStatus,
    ContributorApplication,
    ContributorEarning,
    ContributorKYC,
    ContributorProfile,
    EarningStatus,
    KYCStatus,
    PaywallReadEvent,
    PayoutRequest,
    PayoutRequestEarning,
    PayoutRequestStatus,
    PaywallRevenuePeriod,
    PeriodStatus,
    PlatformRewardSettings,
)
from app.auth.models import User
from app.core.roles import UserRole

logger = logging.getLogger(__name__)


# ─────────────────────────── email helper ────────────────────────────────────

async def _fire_email(coro) -> None:
    """Sends an email as fire-and-forget. Never lets email failure bubble up."""
    try:
        await coro
    except Exception as exc:
        logger.warning("email send failed: %s", exc)


# ─────────────────────────── helpers ─────────────────────────────────────────

def _today() -> date:
    return datetime.now(timezone.utc).date()


async def _get_or_create_settings() -> PlatformRewardSettings:
    settings, _ = await PlatformRewardSettings.get_or_create(id=1)
    return settings


# ─────────────────────────── reward gate ─────────────────────────────────────

async def is_reward_active() -> bool:
    """Returns True only if reward_start_date is set and today >= that date."""
    settings = await _get_or_create_settings()
    if settings.reward_start_date is None:
        return False
    return _today() >= settings.reward_start_date


# ─────────────────────────── eligibility engine ──────────────────────────────

async def evaluate_eligibility(contributor: User) -> bool:
    """
    Runs the full algorithm gate against a contributor and persists the result
    to their ContributorProfile. Returns the resolved eligible flag.

    Short-circuits:
      - If rewards not active → False
      - If profile has an editorial override → use that value
    """
    if not await is_reward_active():
        return False

    try:
        profile = await ContributorProfile.get(contributor_id=contributor.id)
    except DoesNotExist:
        return False

    # Editorial override hard-wins over algorithm.
    if profile.eligibility_override is not None:
        result = profile.eligibility_override
        profile.eligibility_checked_at = datetime.now(timezone.utc)
        profile.pay_worthy_eligible = result
        await profile.save()
        return result

    # ── criterion 1: vesting (≥90 days since first published story) ──────────
    if profile.first_published_story_date is None:
        return await _persist_eligibility(profile, False)
    days_active = (_today() - profile.first_published_story_date).days
    if days_active < 90:
        return await _persist_eligibility(profile, False)

    # ── criterion 2: ≥3 published stories/week average over last 3 months ────
    three_months_ago = _today() - timedelta(days=90)
    published_stories = await ConsoleStory.filter(
        author_id=contributor.id,
        status=ConsoleStoryStatus.publish,
        published_at__gte=datetime.combine(three_months_ago, datetime.min.time()).replace(
            tzinfo=timezone.utc
        ),
    ).count()
    # 13 complete weeks in 91 days
    avg_per_week = published_stories / 13.0
    if avg_per_week < 3.0:
        return await _persist_eligibility(profile, False)

    # ── criterion 3: ≥60% pay-worthy rate in last 30 days ────────────────────
    thirty_days_ago = _today() - timedelta(days=30)
    cutoff_30d = datetime.combine(thirty_days_ago, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    recent_stories = await ConsoleStory.filter(
        author_id=contributor.id,
        status=ConsoleStoryStatus.publish,
        published_at__gte=cutoff_30d,
    ).count()
    pay_worthy_recent = await ConsoleStory.filter(
        author_id=contributor.id,
        status=ConsoleStoryStatus.publish,
        is_pay_worthy=True,
        published_at__gte=cutoff_30d,
    ).count()
    if recent_stories == 0 or (pay_worthy_recent / recent_stories) < 0.60:
        return await _persist_eligibility(profile, False)

    # ── criterion 4: avg editorial_score ≥70 over last 2 months ─────────────
    two_months_ago = _today() - timedelta(days=60)
    cutoff_2m = datetime.combine(two_months_ago, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    scored_stories = await ConsoleStory.filter(
        author_id=contributor.id,
        status=ConsoleStoryStatus.publish,
        published_at__gte=cutoff_2m,
        editorial_score__isnull=False,
    ).values_list("editorial_score", flat=True)
    if not scored_stories:
        return await _persist_eligibility(profile, False)
    avg_score = sum(scored_stories) / len(scored_stories)
    if avg_score < 70.0:
        return await _persist_eligibility(profile, False)

    return await _persist_eligibility(profile, True)


async def _persist_eligibility(profile: ContributorProfile, result: bool) -> bool:
    profile.pay_worthy_eligible = result
    profile.eligibility_checked_at = datetime.now(timezone.utc)
    await profile.save()
    logger.info(
        "eligibility contributor=%s result=%s", profile.contributor_id, result
    )
    return result


# ─────────────────────────── application helpers ─────────────────────────────

async def approve_application(application: ContributorApplication, reviewer: User, note: Optional[str]) -> None:
    """Approve application, create account if needed, create ContributorProfile.
    Role stays 'reader' until KYC is verified."""
    import secrets
    from pwdlib import PasswordHash
    from pwdlib.hashers.bcrypt import BcryptHasher
    from app.core.roles import UserRole
    from app.config import settings
    from app.core.email import email_client

    application.status = ApplicationStatus.approved
    application.reviewer_id = reviewer.id
    application.reviewer_note = note
    application.reviewed_at = datetime.now(timezone.utc)
    await application.save()

    is_new_account = False
    if application.applicant_id:
        applicant = await application.applicant
    else:
        applicant = await User.get_or_none(email=application.email)
        if applicant is None:
            ph = PasswordHash([BcryptHasher()])
            display = f"{application.first_name or ''} {application.last_name or ''}".strip() or None
            # Role stays reader until KYC is approved
            applicant = await User.create(
                email=application.email,
                hashed_password=ph.hash(secrets.token_urlsafe(32)),
                is_active=True,
                is_verified=True,
                display_name=display,
                role=UserRole.reader,
            )
            is_new_account = True
        application.applicant_id = applicant.id
        await application.save()

    # ContributorProfile existence signals application approval; role stays reader until KYC.
    await ContributorProfile.get_or_create(contributor_id=applicant.id)

    kyc_url = f"{settings.FRONTEND_URL}/auth/contributor-kyc"
    if is_new_account:
        await _fire_email(email_client.send_application_approved_new_account(
            applicant.email,
            applicant.display_name or applicant.email,
            f"{settings.FRONTEND_URL}/auth/login",
        ))
    else:
        await _fire_email(email_client.send_application_approved(
            applicant.email,
            applicant.display_name or applicant.email,
            kyc_url,
        ))


async def approve_kyc(kyc: ContributorKYC, reviewer: User) -> None:
    """Verify KYC submission and upgrade contributor role to 'contributor'."""
    from app.core.roles import UserRole
    from app.config import settings
    from app.core.email import email_client

    kyc.status = KYCStatus.approved
    kyc.reviewed_by_id = reviewer.id
    kyc.reviewed_at = datetime.now(timezone.utc)
    await kyc.save()

    contributor = await kyc.contributor
    if contributor.role == UserRole.reader:
        contributor.role = UserRole.contributor
        await contributor.save()

    await _fire_email(email_client.send_kyc_approved(
        contributor.email,
        contributor.display_name or contributor.email,
        f"{settings.FRONTEND_URL}/console",
    ))


async def reject_kyc(kyc: ContributorKYC, reviewer: User, note: Optional[str]) -> None:
    """Reject KYC — contributor must resubmit."""
    from app.config import settings
    from app.core.email import email_client

    kyc.status = KYCStatus.rejected
    kyc.reviewed_by_id = reviewer.id
    kyc.reviewed_at = datetime.now(timezone.utc)
    kyc.reviewer_note = note
    await kyc.save()

    contributor = await kyc.contributor
    await _fire_email(email_client.send_kyc_rejected(
        contributor.email,
        contributor.display_name or contributor.email,
        f"{settings.FRONTEND_URL}/auth/contributor-kyc",
        note,
    ))


async def reject_application(application: ContributorApplication, reviewer: User, note: Optional[str]) -> None:
    from app.core.email import email_client

    application.status = ApplicationStatus.rejected
    application.reviewer_id = reviewer.id
    application.reviewer_note = note
    application.reviewed_at = datetime.now(timezone.utc)
    await application.save()

    if application.applicant_id:
        applicant = await application.applicant
        to_email = applicant.email
        to_name = applicant.display_name or applicant.email
    else:
        to_email = application.email or ""
        to_name = f"{application.first_name or ''} {application.last_name or ''}".strip() or to_email

    await _fire_email(email_client.send_application_rejected(to_email, to_name, note))


# ─────────────────────────── first-publish hook ──────────────────────────────

async def on_story_published(story: ConsoleStory) -> None:
    """
    Call this whenever a story transitions to status=publish.
    Sets first_published_story_date on the contributor's profile if not already set.
    """
    try:
        profile = await ContributorProfile.get(contributor_id=story.author_id)
    except DoesNotExist:
        return
    if profile.first_published_story_date is None:
        profile.first_published_story_date = _today()
        await profile.save()


# ─────────────────────────── eligibility breakdown ───────────────────────────

async def get_eligibility_breakdown(contributor: User) -> dict:
    """
    Returns the per-criterion breakdown for a contributor without persisting.
    Used by GET /contributor/eligibility and the admin evaluate endpoint.
    """
    if not await is_reward_active():
        return {
            "eligible": False,
            "override": None,
            "checked_at": None,
            "reward_active": False,
            "criteria": None,
        }

    try:
        profile = await ContributorProfile.get(contributor_id=contributor.id)
    except Exception:
        return {
            "eligible": False,
            "override": None,
            "checked_at": None,
            "reward_active": True,
            "criteria": None,
        }

    override = profile.eligibility_override

    # ── criterion 1: vesting ─────────────────────────────────────────────────
    days_active = 0
    c1_pass = False
    if profile.first_published_story_date is not None:
        days_active = (_today() - profile.first_published_story_date).days
        c1_pass = days_active >= 90

    # ── criterion 2: stories/week avg over last 3 months ────────────────────
    three_months_ago = _today() - timedelta(days=90)
    published_stories = await ConsoleStory.filter(
        author_id=contributor.id,
        status=ConsoleStoryStatus.publish,
        published_at__gte=datetime.combine(three_months_ago, datetime.min.time()).replace(tzinfo=timezone.utc),
    ).count()
    avg_per_week = round(published_stories / 13.0, 2)
    c2_pass = avg_per_week >= 3.0

    # ── criterion 3: pay-worthy rate in last 30 days ─────────────────────────
    thirty_days_ago = _today() - timedelta(days=30)
    cutoff_30d = datetime.combine(thirty_days_ago, datetime.min.time()).replace(tzinfo=timezone.utc)
    recent_stories = await ConsoleStory.filter(
        author_id=contributor.id, status=ConsoleStoryStatus.publish, published_at__gte=cutoff_30d,
    ).count()
    pay_worthy_recent = await ConsoleStory.filter(
        author_id=contributor.id, status=ConsoleStoryStatus.publish,
        is_pay_worthy=True, published_at__gte=cutoff_30d,
    ).count()
    pw_rate = round(pay_worthy_recent / recent_stories, 2) if recent_stories > 0 else 0.0
    c3_pass = recent_stories > 0 and pw_rate >= 0.60

    # ── criterion 4: avg editorial score over last 2 months ─────────────────
    two_months_ago = _today() - timedelta(days=60)
    cutoff_2m = datetime.combine(two_months_ago, datetime.min.time()).replace(tzinfo=timezone.utc)
    scored = await ConsoleStory.filter(
        author_id=contributor.id, status=ConsoleStoryStatus.publish,
        published_at__gte=cutoff_2m, editorial_score__isnull=False,
    ).values_list("editorial_score", flat=True)
    avg_score = round(sum(scored) / len(scored), 1) if scored else 0.0
    c4_pass = bool(scored) and avg_score >= 70.0

    algo_result = c1_pass and c2_pass and c3_pass and c4_pass
    effective = override if override is not None else algo_result

    return {
        "eligible": effective,
        "override": override,
        "checked_at": profile.eligibility_checked_at,
        "reward_active": True,
        "criteria": {
            "vesting": {"pass": c1_pass, "days_active": days_active, "required": 90},
            "stories_per_week": {"pass": c2_pass, "avg": avg_per_week, "required": 3.0},
            "pay_worthy_rate": {"pass": c3_pass, "rate": pw_rate, "required": 0.60},
            "editorial_score_avg": {"pass": c4_pass, "avg": avg_score, "required": 70.0},
        },
    }


# ─────────────────────────── weekly distribution ─────────────────────────────

async def distribute_period(period: PaywallRevenuePeriod, distributor: User) -> int:
    """
    Compute and persist ContributorEarning rows for all eligible contributors
    who had pay-worthy paywall reads in this period.

    Returns the number of contributor rows created/updated.

    Rules:
      - Rewards gate must be active.
      - Period must be in 'closed' state.
      - Cannot re-distribute if any earnings are already approved or paid.
      - Uses PaywallReadEvent (timestamped per-reader rows) for period-scoped read counts.
      - Uses period.revenue_share_pct (locked at creation) not live settings.
      - Only pay_worthy_eligible contributors are included.
    """
    if not await is_reward_active():
        raise ValueError("Rewards are not active yet. Set reward_start_date first.")

    if period.status != PeriodStatus.closed:
        raise ValueError("Period must be in 'closed' state before distribution.")

    # Guard: do not overwrite already-approved or paid earnings.
    already_final = await ContributorEarning.filter(
        period=period, status__in=[EarningStatus.approved, EarningStatus.paid]
    ).exists()
    if already_final:
        raise ValueError(
            "Cannot re-distribute: this period already has approved or paid earnings."
        )

    # Use the share % locked at period creation, not live settings.
    share_pct = period.revenue_share_pct
    pool = (period.gross_paywall_revenue * share_pct).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    period_start_dt = datetime.combine(period.week_start, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    period_end_dt = datetime.combine(period.week_end, datetime.max.time()).replace(
        tzinfo=timezone.utc
    )

    # Get all pay-worthy stories published within this period.
    stories = await ConsoleStory.filter(
        is_pay_worthy=True,
        status=ConsoleStoryStatus.publish,
        published_at__gte=period_start_dt,
        published_at__lte=period_end_dt,
    ).values_list("id", "author_id", flat=False)

    story_ids = [s[0] for s in stories]
    story_author_map: dict = {s[0]: s[1] for s in stories}

    # Filter to only pay_worthy_eligible contributors.
    eligible_contributor_ids = set(
        await ContributorProfile.filter(pay_worthy_eligible=True).values_list(
            "contributor_id", flat=True
        )
    )

    if not story_ids:
        period.contributor_pool = Decimal("0.00")
        period.status = PeriodStatus.distributed
        period.distributed_at = datetime.now(timezone.utc)
        period.distributed_by_id = distributor.id
        await period.save()
        return 0

    # Count PaywallReadEvents per story within the period window.
    read_events = await PaywallReadEvent.filter(
        console_story_id__in=story_ids,
        read_at__gte=period_start_dt,
        read_at__lte=period_end_dt,
    ).values_list("console_story_id", flat=True)

    # Aggregate reads per eligible contributor.
    reads_by_contributor: dict = {}
    for story_id in read_events:
        author_id = story_author_map.get(story_id)
        if author_id is None or author_id not in eligible_contributor_ids:
            continue
        reads_by_contributor[author_id] = reads_by_contributor.get(author_id, 0) + 1

    pool_total_reads = sum(reads_by_contributor.values())

    if pool_total_reads == 0:
        period.contributor_pool = Decimal("0.00")
        period.status = PeriodStatus.distributed
        period.distributed_at = datetime.now(timezone.utc)
        period.distributed_by_id = distributor.id
        await period.save()
        return 0

    rows_written = 0
    for contributor_id, reads in reads_by_contributor.items():
        share = (pool * Decimal(reads) / Decimal(pool_total_reads)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        earning, created = await ContributorEarning.get_or_create(
            contributor_id=contributor_id,
            period=period,
            defaults={
                "paywall_reads": reads,
                "pool_total_reads": pool_total_reads,
                "gross_amount": share,
                "status": EarningStatus.pending,
            },
        )
        if not created:
            # Only overwrite if still pending (guard above ensures no approved/paid exist).
            earning.paywall_reads = reads
            earning.pool_total_reads = pool_total_reads
            earning.gross_amount = share
            earning.status = EarningStatus.pending
            await earning.save()
        rows_written += 1

    period.contributor_pool = pool
    period.status = PeriodStatus.distributed
    period.distributed_at = datetime.now(timezone.utc)
    period.distributed_by_id = distributor.id
    await period.save()

    logger.info(
        "distribution period=%s pool=₦%s contributors=%d total_reads=%d",
        period.id, pool, rows_written, pool_total_reads,
    )

    # Send each earning contributor a notification email + in-app notification.
    from app.config import settings
    from app.core.email import email_client
    from app.notifications.models import NotificationType
    from app.notifications.service import create_notification as _notify
    week_start_str = period.week_start.strftime("%d %b %Y")
    week_end_str = period.week_end.strftime("%d %b %Y")
    for contributor_id in reads_by_contributor:
        user = await User.get_or_none(id=contributor_id)
        if not user:
            continue
        earning = await ContributorEarning.get_or_none(contributor_id=contributor_id, period=period)
        if not earning:
            continue
        await _fire_email(email_client.send_earnings_distributed(
            user.email,
            user.display_name or user.email,
            week_start_str,
            week_end_str,
            f"{earning.gross_amount:,.2f}",
            f"{settings.FRONTEND_URL}/console/earnings",
        ))
        try:
            amount_str = f"₦{float(earning.gross_amount):,.2f}"
            await _notify(
                recipient_id=user.id,
                notif_type=NotificationType.earning_distributed,
                title="Earnings distributed for this period",
                body=f"{amount_str} has been distributed for the period {week_start_str} – {week_end_str}. Review and approve to request payout.",
                link="/console/earnings",
                sender_id=distributor.id,
            )
        except Exception:
            pass

    return rows_written


# ─────────────────────────── earnings admin actions ──────────────────────────

async def approve_earning(earning: ContributorEarning, admin: User, send_email: bool = True) -> None:
    if earning.status != EarningStatus.pending:
        raise ValueError(f"Cannot approve earning with status '{earning.status}'")
    earning.status = EarningStatus.approved
    await earning.save()

    if send_email:
        from app.config import settings
        from app.core.email import email_client
        contributor = await earning.contributor
        await _fire_email(email_client.send_earning_approved(
            contributor.email,
            contributor.display_name or contributor.email,
            f"{earning.gross_amount:,.2f}",
            f"{settings.FRONTEND_URL}/console/earnings",
        ))


async def reject_earning(earning: ContributorEarning, admin: User, note: str) -> None:
    if earning.status != EarningStatus.pending:
        raise ValueError(f"Cannot reject earning with status '{earning.status}'")
    earning.status = EarningStatus.rejected
    await earning.save()


# ─────────────────────────── payout workflow ─────────────────────────────────

MINIMUM_PAYOUT_NAIRA = Decimal("5000.00")


async def create_payout_request(contributor: User) -> "PayoutRequest":
    from app.contributors.models import ContributorBankAccount

    try:
        bank = await ContributorBankAccount.get(contributor_id=contributor.id)
    except Exception:
        raise ValueError("Bank account not set up. Add your bank account details first.")

    # Collect all approved earnings not already in an active payout request.
    in_flight_earning_ids = set(
        await PayoutRequestEarning.filter(
            payout_request__status__in=[
                PayoutRequestStatus.pending_admin,
                PayoutRequestStatus.approved,
                PayoutRequestStatus.processing,
            ]
        ).values_list("earning_id", flat=True)
    )

    approved_earnings = await ContributorEarning.filter(
        contributor_id=contributor.id,
        status=EarningStatus.approved,
    )
    claimable = [e for e in approved_earnings if e.id not in in_flight_earning_ids]

    if not claimable:
        raise ValueError("No approved earnings available to request payout for.")

    total = sum(e.gross_amount for e in claimable)
    if total < MINIMUM_PAYOUT_NAIRA:
        raise ValueError(
            f"Minimum payout is ₦{MINIMUM_PAYOUT_NAIRA:,.0f}. "
            f"Your approved total is ₦{total:,.2f}."
        )

    bank_snapshot = {
        "account_name": bank.account_name,
        "bank_name": bank.bank_name,
        "bank_code": bank.bank_code,
        "account_number_masked": f"****{bank.account_number[-4:]}",
    }

    payout = await PayoutRequest.create(
        contributor_id=contributor.id,
        requested_amount=total,
        bank_account_snapshot=bank_snapshot,
    )
    for earning in claimable:
        await PayoutRequestEarning.create(payout_request=payout, earning=earning)

    logger.info(
        "payout_request contributor=%s amount=₦%s earnings=%d",
        contributor.id, total, len(claimable),
    )
    return payout


async def approve_payout_request(payout: "PayoutRequest", admin: User, note: Optional[str]) -> None:
    if payout.status != PayoutRequestStatus.pending_admin:
        raise ValueError(f"Cannot approve payout with status '{payout.status}'")
    payout.status = PayoutRequestStatus.approved
    payout.approved_by_id = admin.id
    payout.approved_at = datetime.now(timezone.utc)
    payout.admin_note = note
    await payout.save()

    from app.core.email import email_client
    contributor = await payout.contributor
    await _fire_email(email_client.send_payout_approved(
        contributor.email,
        contributor.display_name or contributor.email,
        f"{payout.requested_amount:,.2f}",
    ))


async def reject_payout_request(payout: "PayoutRequest", admin: User, note: str) -> None:
    if payout.status not in (PayoutRequestStatus.pending_admin, PayoutRequestStatus.approved):
        raise ValueError(f"Cannot reject payout with status '{payout.status}'")
    payout.status = PayoutRequestStatus.rejected
    payout.admin_note = note
    await payout.save()


async def mark_payout_paid(payout: "PayoutRequest", admin: User) -> None:
    """Manual mark-paid — used when Paystack is not configured or as fallback."""
    if payout.status not in (PayoutRequestStatus.approved, PayoutRequestStatus.processing):
        raise ValueError(f"Cannot mark as paid a payout with status '{payout.status}'")
    await _complete_payout(payout, sender_id=admin.id)


async def initiate_payout_transfer(payout: "PayoutRequest", transfer_code: str) -> None:
    """Called after a Paystack transfer is successfully initiated. Moves to processing."""
    payout.status = PayoutRequestStatus.processing
    payout.paystack_transfer_code = transfer_code
    await payout.save()


async def complete_payout_paid(payout: "PayoutRequest") -> None:
    """Called by the Paystack webhook on transfer.success."""
    if payout.status != PayoutRequestStatus.processing:
        return
    await _complete_payout(payout)


async def fail_payout(payout: "PayoutRequest", reason: Optional[str] = None) -> None:
    """Called by the Paystack webhook on transfer.failed or transfer.reversed."""
    if payout.status != PayoutRequestStatus.processing:
        return
    payout.status = PayoutRequestStatus.failed
    if reason:
        payout.admin_note = f"Transfer failed: {reason}"
    await payout.save()

    contributor = await payout.contributor
    from app.core.email import email_client
    await _fire_email(email_client.send_payout_failed(
        contributor.email,
        contributor.display_name or contributor.email,
        f"{payout.requested_amount:,.2f}",
        reason,
    ))
    try:
        from app.notifications.models import NotificationType
        from app.notifications.service import create_notification as _notify
        amount_str = f"₦{float(payout.requested_amount):,.2f}"
        reason_str = f" Reason: {reason}" if reason else ""
        await _notify(
            recipient_id=contributor.id,
            notif_type=NotificationType.payout_failed,
            title="Payout transfer failed",
            body=f"Your payout of {amount_str} could not be processed.{reason_str} Please contact support.",
            link="/console/payout-requests",
        )
    except Exception:
        pass


async def _complete_payout(payout: "PayoutRequest", sender_id=None) -> None:
    """Shared logic: move payout to paid, cascade earnings, send confirmation email + notification."""
    payout.status = PayoutRequestStatus.paid
    payout.paid_at = datetime.now(timezone.utc)
    await payout.save()

    earning_ids = await PayoutRequestEarning.filter(
        payout_request=payout
    ).values_list("earning_id", flat=True)
    await ContributorEarning.filter(id__in=list(earning_ids)).update(status=EarningStatus.paid)

    from app.core.email import email_client
    contributor = await payout.contributor
    snapshot = payout.bank_account_snapshot
    await _fire_email(email_client.send_payout_paid(
        contributor.email,
        contributor.display_name or contributor.email,
        f"{payout.requested_amount:,.2f}",
        snapshot.get("bank_name", ""),
        snapshot.get("account_number_masked", "****"),
    ))
    try:
        from app.notifications.models import NotificationType
        from app.notifications.service import create_notification as _notify
        amount_str = f"₦{float(payout.requested_amount):,.2f}"
        await _notify(
            recipient_id=contributor.id,
            notif_type=NotificationType.payout_paid,
            title="Payment sent",
            body=f"Your payout of {amount_str} has been disbursed to your bank account.",
            link="/console/payout-requests",
            sender_id=sender_id,
        )
    except Exception:
        pass
