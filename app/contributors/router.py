"""
Contributors router — all contributor + admin endpoints for the reward system.

Contributor surface (role >= contributor):
  POST  /api/contributor/apply
  GET   /api/contributor/application
  GET   /api/contributor/profile
  GET   /api/contributor/eligibility
  GET   /api/contributor/earnings
  GET   /api/contributor/bank-account
  POST  /api/contributor/bank-account
  DELETE /api/contributor/bank-account
  GET   /api/contributor/payout-requests
  POST  /api/contributor/payout-requests

Admin surface (role >= admin):
  GET   /api/admin/contributor/applications
  PATCH /api/admin/contributor/applications/{id}
  GET   /api/admin/contributor/reward-settings
  PATCH /api/admin/contributor/reward-settings
  GET   /api/admin/contributor/periods
  POST  /api/admin/contributor/periods
  PATCH /api/admin/contributor/periods/{id}/revenue
  PATCH /api/admin/contributor/periods/{id}/close
  POST  /api/admin/contributor/periods/{id}/distribute
  GET   /api/admin/contributor/earnings
  PATCH /api/admin/contributor/earnings/{id}
  POST  /api/admin/contributor/earnings/bulk-approve
  PATCH /api/admin/contributor/profiles/{user_id}/eligibility-override
  POST  /api/admin/contributor/profiles/{user_id}/evaluate
  POST  /api/admin/contributor/profiles/evaluate-batch
  GET   /api/admin/contributor/payout-requests
  PATCH /api/admin/contributor/payout-requests/{id}
  PATCH /api/admin/contributor/payout-requests/{id}/mark-paid

Story pay-worthy gating (role >= editor):
  PATCH /api/admin/stories/{story_id}/pay-worthy
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth.dependencies import current_active_user
from app.auth.models import User
from app.console.models import ConsoleStory
from app.contributors.models import (
    ApplicationStatus,
    ContributorApplication,
    ContributorBankAccount,
    ContributorEarning,
    ContributorProfile,
    EarningStatus,
    PayoutRequest,
    PayoutRequestEarning,
    PayoutRequestStatus,
    PaywallRevenuePeriod,
    PeriodStatus,
    PlatformRewardSettings,
)
from app.contributors.schemas import (
    ApplicationAdminRead,
    ApplicationRead,
    ApplicationReview,
    ApplicationSubmit,
    BankAccountCreate,
    BankAccountRead,
    BulkEarningApprove,
    ContributorProfileRead,
    EarningAdminRead,
    EarningRead,
    EarningReview,
    EarningsSummary,
    EligibilityBreakdown,
    EligibilityOverrideUpdate,
    PayWorthyRubric,
    PayoutRequestAdminRead,
    PayoutRequestRead,
    PayoutRequestReview,
    PeriodCreate,
    PeriodRead,
    PeriodRevenueUpdate,
    RewardSettingsRead,
    RewardSettingsUpdate,
    StoryPayWorthyUpdate,
)
from app.contributors import service
from app.core.roles import UserRole, role_has_at_least

router = APIRouter(prefix="/api")


# ── role guards ───────────────────────────────────────────────────────────────

def _require_contributor(user: User = Depends(current_active_user)) -> User:
    if not role_has_at_least(user.role, UserRole.contributor):
        raise HTTPException(403, "Contributor role required")
    return user


def _require_editor(user: User = Depends(current_active_user)) -> User:
    if not role_has_at_least(user.role, UserRole.editor):
        raise HTTPException(403, "Editor role required")
    return user


def _require_admin(user: User = Depends(current_active_user)) -> User:
    if not role_has_at_least(user.role, UserRole.admin):
        raise HTTPException(403, "Admin role required")
    return user


# ── helpers ───────────────────────────────────────────────────────────────────

def _earning_to_read(e: ContributorEarning, period: PaywallRevenuePeriod) -> EarningRead:
    pool = period.contributor_pool
    share_pct = (
        Decimal(e.paywall_reads) / Decimal(e.pool_total_reads)
        if e.pool_total_reads > 0
        else Decimal("0")
    )
    return EarningRead(
        id=e.id,
        period_id=period.id,
        week_start=period.week_start,
        week_end=period.week_end,
        paywall_reads=e.paywall_reads,
        pool_total_reads=e.pool_total_reads,
        contributor_pool=pool,
        share_pct=share_pct.quantize(Decimal("0.0001")),
        gross_amount=e.gross_amount,
        status=e.status,
    )


async def _payout_to_read(payout: PayoutRequest) -> PayoutRequestRead:
    count = await PayoutRequestEarning.filter(payout_request=payout).count()
    return PayoutRequestRead(
        id=payout.id,
        requested_amount=payout.requested_amount,
        bank_account_snapshot=payout.bank_account_snapshot,
        status=payout.status,
        admin_note=payout.admin_note,
        approved_at=payout.approved_at,
        paid_at=payout.paid_at,
        created_at=payout.created_at,
        earnings_count=count,
    )


async def _payout_to_admin_read(payout: PayoutRequest) -> PayoutRequestAdminRead:
    contributor = await payout.contributor
    count = await PayoutRequestEarning.filter(payout_request=payout).count()
    return PayoutRequestAdminRead(
        id=payout.id,
        contributor_id=contributor.id,
        contributor_email=contributor.email,
        contributor_name=contributor.display_name,
        requested_amount=payout.requested_amount,
        bank_account_snapshot=payout.bank_account_snapshot,
        status=payout.status,
        admin_note=payout.admin_note,
        approved_at=payout.approved_at,
        paid_at=payout.paid_at,
        created_at=payout.created_at,
        earnings_count=count,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CONTRIBUTOR — APPLICATION
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/contributor/apply",
    response_model=ApplicationRead,
    status_code=201,
    tags=["contributor"],
)
async def submit_application(
    body: ApplicationSubmit,
    current_user: User = Depends(current_active_user),
) -> ContributorApplication:
    # Block if a pending or approved application already exists.
    # Rejected applicants may re-apply (a new row is created).
    existing = await ContributorApplication.filter(
        applicant_id=current_user.id,
        status__in=[ApplicationStatus.pending, ApplicationStatus.approved],
    ).first()
    if existing:
        raise HTTPException(409, "You already have a pending or approved application.")
    return await ContributorApplication.create(
        applicant_id=current_user.id,
        bio=body.bio,
        portfolio_url=body.portfolio_url,
        coverage_areas=body.coverage_areas,
        verticals=body.verticals,
        kyc_document_type=body.kyc_document_type,
        kyc_document_ref=body.kyc_document_ref,
    )


@router.get(
    "/contributor/application",
    response_model=ApplicationRead,
    tags=["contributor"],
)
async def get_my_application(
    current_user: User = Depends(current_active_user),
) -> ContributorApplication:
    app = (
        await ContributorApplication.filter(applicant_id=current_user.id)
        .order_by("-submitted_at")
        .first()
    )
    if not app:
        raise HTTPException(404, "No application found")
    return app


# ══════════════════════════════════════════════════════════════════════════════
# CONTRIBUTOR — PROFILE & ELIGIBILITY
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/contributor/profile",
    response_model=ContributorProfileRead,
    tags=["contributor"],
)
async def get_my_profile(
    current_user: User = Depends(_require_contributor),
) -> ContributorProfile:
    profile = await ContributorProfile.get_or_none(contributor_id=current_user.id)
    if not profile:
        raise HTTPException(404, "Contributor profile not found")
    return profile


@router.get(
    "/contributor/eligibility",
    response_model=EligibilityBreakdown,
    tags=["contributor"],
)
async def get_my_eligibility(
    current_user: User = Depends(_require_contributor),
) -> EligibilityBreakdown:
    breakdown = await service.get_eligibility_breakdown(current_user)
    return EligibilityBreakdown(**breakdown)


# ══════════════════════════════════════════════════════════════════════════════
# CONTRIBUTOR — EARNINGS
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/contributor/earnings",
    response_model=EarningsSummary,
    tags=["contributor"],
)
async def get_my_earnings(
    current_user: User = Depends(_require_contributor),
) -> EarningsSummary:
    raw = await ContributorEarning.filter(
        contributor_id=current_user.id
    ).prefetch_related("period").order_by("-created_at")

    total_pending = sum(e.gross_amount for e in raw if e.status == EarningStatus.pending)
    total_approved = sum(e.gross_amount for e in raw if e.status == EarningStatus.approved)
    total_paid = sum(e.gross_amount for e in raw if e.status == EarningStatus.paid)

    earnings = [_earning_to_read(e, await e.period) for e in raw]

    return EarningsSummary(
        total_pending=total_pending or Decimal("0"),
        total_approved=total_approved or Decimal("0"),
        total_paid=total_paid or Decimal("0"),
        earnings=earnings,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CONTRIBUTOR — BANK ACCOUNT
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/contributor/bank-account",
    response_model=BankAccountRead,
    tags=["contributor"],
)
async def get_my_bank_account(
    current_user: User = Depends(_require_contributor),
) -> BankAccountRead:
    bank = await ContributorBankAccount.get_or_none(contributor_id=current_user.id)
    if not bank:
        raise HTTPException(404, "No bank account on file")
    return BankAccountRead(
        id=bank.id,
        account_name=bank.account_name,
        bank_code=bank.bank_code,
        bank_name=bank.bank_name,
        account_number_masked=f"****{bank.account_number[-4:]}",
        is_verified=bank.is_verified,
        created_at=bank.created_at,
        updated_at=bank.updated_at,
    )


@router.post(
    "/contributor/bank-account",
    response_model=BankAccountRead,
    status_code=201,
    tags=["contributor"],
)
async def save_bank_account(
    body: BankAccountCreate,
    current_user: User = Depends(_require_contributor),
) -> BankAccountRead:
    from app.config import settings
    from app.core import paystack as paystack_client

    verified_name = body.account_name
    recipient_code = None
    is_verified = False

    if settings.paystack_live:
        try:
            verified_name = await paystack_client.resolve_account(body.account_number, body.bank_code)
            recipient_code = await paystack_client.create_transfer_recipient(
                verified_name, body.account_number, body.bank_code, body.bank_name
            )
            is_verified = True
        except Exception as exc:
            raise HTTPException(422, f"Bank account verification failed: {exc}")

    # Replace existing account (delete + create).
    await ContributorBankAccount.filter(contributor_id=current_user.id).delete()
    bank = await ContributorBankAccount.create(
        contributor_id=current_user.id,
        account_name=verified_name,
        bank_code=body.bank_code,
        bank_name=body.bank_name,
        account_number=body.account_number,
        is_verified=is_verified,
        paystack_recipient_code=recipient_code,
    )
    return BankAccountRead(
        id=bank.id,
        account_name=bank.account_name,
        bank_code=bank.bank_code,
        bank_name=bank.bank_name,
        account_number_masked=f"****{bank.account_number[-4:]}",
        is_verified=bank.is_verified,
        created_at=bank.created_at,
        updated_at=bank.updated_at,
    )


@router.delete(
    "/contributor/bank-account",
    status_code=204,
    tags=["contributor"],
)
async def delete_bank_account(
    current_user: User = Depends(_require_contributor),
) -> None:
    deleted = await ContributorBankAccount.filter(
        contributor_id=current_user.id
    ).delete()
    if not deleted:
        raise HTTPException(404, "No bank account on file")


# ══════════════════════════════════════════════════════════════════════════════
# CONTRIBUTOR — PAYOUT REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/contributor/payout-requests",
    response_model=list[PayoutRequestRead],
    tags=["contributor"],
)
async def list_my_payout_requests(
    current_user: User = Depends(_require_contributor),
) -> list[PayoutRequestRead]:
    payouts = await PayoutRequest.filter(
        contributor_id=current_user.id
    ).order_by("-created_at")
    return [await _payout_to_read(p) for p in payouts]


@router.post(
    "/contributor/payout-requests",
    response_model=PayoutRequestRead,
    status_code=201,
    tags=["contributor"],
)
async def create_payout_request(
    current_user: User = Depends(_require_contributor),
) -> PayoutRequestRead:
    try:
        payout = await service.create_payout_request(current_user)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return await _payout_to_read(payout)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — APPLICATIONS
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/admin/contributor/applications",
    response_model=list[ApplicationAdminRead],
    tags=["admin"],
)
async def list_applications(
    status: Optional[ApplicationStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _admin: User = Depends(_require_admin),
) -> list[ApplicationAdminRead]:
    qs = ContributorApplication.all().prefetch_related("applicant")
    if status:
        qs = qs.filter(status=status)
    apps = await qs.offset(skip).limit(limit)
    result = []
    for a in apps:
        applicant = await a.applicant
        result.append(ApplicationAdminRead(
            id=a.id,
            applicant_id=applicant.id,
            applicant_email=applicant.email,
            applicant_name=applicant.display_name,
            bio=a.bio,
            portfolio_url=a.portfolio_url,
            coverage_areas=a.coverage_areas,
            verticals=a.verticals,
            kyc_document_type=a.kyc_document_type,
            kyc_document_ref=a.kyc_document_ref,
            status=a.status,
            submitted_at=a.submitted_at,
            reviewed_at=a.reviewed_at,
            reviewer_note=a.reviewer_note,
        ))
    return result


@router.patch(
    "/admin/contributor/applications/{application_id}",
    response_model=ApplicationAdminRead,
    tags=["admin"],
)
async def review_application(
    application_id: uuid.UUID,
    body: ApplicationReview,
    admin: User = Depends(_require_admin),
) -> ApplicationAdminRead:
    app = await ContributorApplication.get_or_none(id=application_id)
    if not app:
        raise HTTPException(404, "Application not found")
    if app.status != ApplicationStatus.pending:
        raise HTTPException(409, "Application has already been reviewed")
    if body.status == ApplicationStatus.approved:
        await service.approve_application(app, admin, body.reviewer_note)
    elif body.status == ApplicationStatus.rejected:
        await service.reject_application(app, admin, body.reviewer_note)
    else:
        raise HTTPException(400, "status must be 'approved' or 'rejected'")

    applicant = await app.applicant
    return ApplicationAdminRead(
        id=app.id,
        applicant_id=applicant.id,
        applicant_email=applicant.email,
        applicant_name=applicant.display_name,
        bio=app.bio,
        portfolio_url=app.portfolio_url,
        coverage_areas=app.coverage_areas,
        verticals=app.verticals,
        kyc_document_type=app.kyc_document_type,
        kyc_document_ref=app.kyc_document_ref,
        status=app.status,
        submitted_at=app.submitted_at,
        reviewed_at=app.reviewed_at,
        reviewer_note=app.reviewer_note,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — REWARD SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/admin/contributor/reward-settings",
    response_model=RewardSettingsRead,
    tags=["admin"],
)
async def get_reward_settings(
    _admin: User = Depends(_require_admin),
) -> PlatformRewardSettings:
    settings, _ = await PlatformRewardSettings.get_or_create(id=1)
    return settings


@router.patch(
    "/admin/contributor/reward-settings",
    response_model=RewardSettingsRead,
    tags=["admin"],
)
async def update_reward_settings(
    body: RewardSettingsUpdate,
    admin: User = Depends(_require_admin),
) -> PlatformRewardSettings:
    settings, _ = await PlatformRewardSettings.get_or_create(id=1)
    if body.reward_start_date is not None:
        settings.reward_start_date = body.reward_start_date
    if body.contributor_revenue_share is not None:
        settings.contributor_revenue_share = body.contributor_revenue_share
    settings.updated_by_id = admin.id
    await settings.save()
    return settings


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — REVENUE PERIODS
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/admin/contributor/periods",
    response_model=list[PeriodRead],
    tags=["admin"],
)
async def list_periods(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=52),
    _admin: User = Depends(_require_admin),
) -> list[PaywallRevenuePeriod]:
    return await PaywallRevenuePeriod.all().offset(skip).limit(limit)


@router.post(
    "/admin/contributor/periods",
    response_model=PeriodRead,
    status_code=201,
    tags=["admin"],
)
async def create_period(
    body: PeriodCreate,
    _admin: User = Depends(_require_admin),
) -> PaywallRevenuePeriod:
    if body.week_end <= body.week_start:
        raise HTTPException(400, "week_end must be after week_start")
    overlapping = await PaywallRevenuePeriod.filter(
        week_start__lte=body.week_end,
        week_end__gte=body.week_start,
    ).first()
    if overlapping:
        raise HTTPException(409, "A period overlapping those dates already exists")
    settings, _ = await PlatformRewardSettings.get_or_create(id=1)
    return await PaywallRevenuePeriod.create(
        week_start=body.week_start,
        week_end=body.week_end,
        gross_paywall_revenue=body.gross_paywall_revenue,
        revenue_share_pct=settings.contributor_revenue_share,
    )


@router.patch(
    "/admin/contributor/periods/{period_id}/revenue",
    response_model=PeriodRead,
    tags=["admin"],
)
async def update_period_revenue(
    period_id: uuid.UUID,
    body: PeriodRevenueUpdate,
    _admin: User = Depends(_require_admin),
) -> PaywallRevenuePeriod:
    period = await PaywallRevenuePeriod.get_or_none(id=period_id)
    if not period:
        raise HTTPException(404, "Period not found")
    if period.status != PeriodStatus.open:
        raise HTTPException(409, "Revenue can only be updated on open periods")
    period.gross_paywall_revenue = body.gross_paywall_revenue
    await period.save()
    return period


@router.patch(
    "/admin/contributor/periods/{period_id}/close",
    response_model=PeriodRead,
    tags=["admin"],
)
async def close_period(
    period_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
) -> PaywallRevenuePeriod:
    period = await PaywallRevenuePeriod.get_or_none(id=period_id)
    if not period:
        raise HTTPException(404, "Period not found")
    if period.status != PeriodStatus.open:
        raise HTTPException(409, "Period is not open")
    period.status = PeriodStatus.closed
    await period.save()
    return period


@router.post(
    "/admin/contributor/periods/{period_id}/distribute",
    tags=["admin"],
)
async def distribute_period(
    period_id: uuid.UUID,
    admin: User = Depends(_require_admin),
) -> dict:
    period = await PaywallRevenuePeriod.get_or_none(id=period_id)
    if not period:
        raise HTTPException(404, "Period not found")
    try:
        count = await service.distribute_period(period, admin)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"contributors_paid": count, "period_id": str(period_id)}


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — EARNINGS
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/admin/contributor/earnings",
    response_model=list[EarningAdminRead],
    tags=["admin"],
)
async def list_earnings(
    period_id: Optional[uuid.UUID] = Query(None),
    status: Optional[EarningStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(_require_admin),
) -> list[EarningAdminRead]:
    qs = ContributorEarning.all().prefetch_related("contributor", "period")
    if period_id:
        qs = qs.filter(period_id=period_id)
    if status:
        qs = qs.filter(status=status)
    rows = await qs.offset(skip).limit(limit)

    result = []
    for e in rows:
        contributor = await e.contributor
        period = await e.period
        pool = period.contributor_pool
        share_pct = (
            Decimal(e.paywall_reads) / Decimal(e.pool_total_reads)
            if e.pool_total_reads > 0
            else Decimal("0")
        )
        result.append(EarningAdminRead(
            id=e.id,
            contributor_id=contributor.id,
            contributor_email=contributor.email,
            contributor_name=contributor.display_name,
            period_id=period.id,
            week_start=period.week_start,
            week_end=period.week_end,
            paywall_reads=e.paywall_reads,
            pool_total_reads=e.pool_total_reads,
            contributor_pool=pool,
            share_pct=share_pct.quantize(Decimal("0.0001")),
            gross_amount=e.gross_amount,
            status=e.status,
        ))
    return result


@router.patch(
    "/admin/contributor/earnings/{earning_id}",
    response_model=EarningAdminRead,
    tags=["admin"],
)
async def review_earning(
    earning_id: uuid.UUID,
    body: EarningReview,
    admin: User = Depends(_require_admin),
) -> EarningAdminRead:
    earning = await ContributorEarning.get_or_none(id=earning_id)
    if not earning:
        raise HTTPException(404, "Earning not found")
    try:
        if body.status == EarningStatus.approved:
            await service.approve_earning(earning, admin)
        elif body.status == EarningStatus.rejected:
            if not body.note:
                raise HTTPException(400, "A note is required when rejecting an earning")
            await service.reject_earning(earning, admin, body.note)
        else:
            raise HTTPException(400, "status must be 'approved' or 'rejected'")
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    contributor = await earning.contributor
    period = await earning.period
    pool = period.contributor_pool
    share_pct = (
        Decimal(earning.paywall_reads) / Decimal(earning.pool_total_reads)
        if earning.pool_total_reads > 0
        else Decimal("0")
    )
    return EarningAdminRead(
        id=earning.id,
        contributor_id=contributor.id,
        contributor_email=contributor.email,
        contributor_name=contributor.display_name,
        period_id=period.id,
        week_start=period.week_start,
        week_end=period.week_end,
        paywall_reads=earning.paywall_reads,
        pool_total_reads=earning.pool_total_reads,
        contributor_pool=pool,
        share_pct=share_pct.quantize(Decimal("0.0001")),
        gross_amount=earning.gross_amount,
        status=earning.status,
    )


@router.post(
    "/admin/contributor/earnings/bulk-approve",
    tags=["admin"],
)
async def bulk_approve_earnings(
    body: BulkEarningApprove,
    admin: User = Depends(_require_admin),
) -> dict:
    from app.config import settings
    from app.core.email import email_client
    from app.contributors.service import _fire_email

    pending = await ContributorEarning.filter(
        period_id=body.period_id, status=EarningStatus.pending
    )
    if not pending:
        raise HTTPException(404, "No pending earnings found for this period")

    count = 0
    approved_by_contributor: dict = {}
    for e in pending:
        try:
            await service.approve_earning(e, admin, send_email=False)
            count += 1
            approved_by_contributor[str(e.contributor_id)] = (
                approved_by_contributor.get(str(e.contributor_id), Decimal("0")) + e.gross_amount
            )
        except ValueError:
            pass

    # Send one consolidated email per contributor.
    for contributor_id_str, total in approved_by_contributor.items():
        from app.auth.models import User as UserModel
        user = await UserModel.get_or_none(id=contributor_id_str)
        if user:
            await _fire_email(email_client.send_earning_approved(
                user.email,
                user.display_name or user.email,
                f"{total:,.2f}",
                f"{settings.FRONTEND_URL}/console/earnings",
            ))

    return {"approved": count, "period_id": str(body.period_id)}


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — ELIGIBILITY
# ══════════════════════════════════════════════════════════════════════════════

@router.patch(
    "/admin/contributor/profiles/{user_id}/eligibility-override",
    response_model=ContributorProfileRead,
    tags=["admin"],
)
async def override_eligibility(
    user_id: uuid.UUID,
    body: EligibilityOverrideUpdate,
    admin: User = Depends(_require_admin),
) -> ContributorProfile:
    profile = await ContributorProfile.get_or_none(contributor_id=user_id)
    if not profile:
        raise HTTPException(404, "Contributor profile not found")
    profile.eligibility_override = body.override
    profile.eligibility_override_by_id = admin.id
    profile.eligibility_override_at = datetime.now(timezone.utc)
    profile.eligibility_override_note = body.note
    if body.override is not None:
        profile.pay_worthy_eligible = body.override
    await profile.save()
    return profile


@router.post(
    "/admin/contributor/profiles/{user_id}/evaluate",
    response_model=EligibilityBreakdown,
    tags=["admin"],
)
async def evaluate_contributor(
    user_id: uuid.UUID,
    admin: User = Depends(_require_admin),
) -> EligibilityBreakdown:
    from app.auth.models import User as UserModel
    user = await UserModel.get_or_none(id=user_id)
    if not user:
        raise HTTPException(404, "User not found")
    # Run algorithm and persist the result.
    await service.evaluate_eligibility(user)
    breakdown = await service.get_eligibility_breakdown(user)
    return EligibilityBreakdown(**breakdown)


@router.post(
    "/admin/contributor/profiles/evaluate-batch",
    tags=["admin"],
)
async def evaluate_all_contributors(
    _admin: User = Depends(_require_admin),
) -> dict:
    from app.auth.models import User as UserModel
    profiles = await ContributorProfile.all().values_list("contributor_id", flat=True)
    eligible = 0
    ineligible = 0
    for uid in profiles:
        user = await UserModel.get_or_none(id=uid)
        if user:
            result = await service.evaluate_eligibility(user)
            if result:
                eligible += 1
            else:
                ineligible += 1
    return {"evaluated": eligible + ineligible, "eligible": eligible, "ineligible": ineligible}


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — PAYOUT REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/admin/contributor/payout-requests",
    response_model=list[PayoutRequestAdminRead],
    tags=["admin"],
)
async def list_payout_requests(
    status: Optional[PayoutRequestStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(_require_admin),
) -> list[PayoutRequestAdminRead]:
    qs = PayoutRequest.all()
    if status:
        qs = qs.filter(status=status)
    payouts = await qs.offset(skip).limit(limit).order_by("-created_at")
    return [await _payout_to_admin_read(p) for p in payouts]


@router.patch(
    "/admin/contributor/payout-requests/{payout_id}",
    response_model=PayoutRequestAdminRead,
    tags=["admin"],
)
async def review_payout_request(
    payout_id: uuid.UUID,
    body: PayoutRequestReview,
    admin: User = Depends(_require_admin),
) -> PayoutRequestAdminRead:
    payout = await PayoutRequest.get_or_none(id=payout_id)
    if not payout:
        raise HTTPException(404, "Payout request not found")
    try:
        if body.action == "approve":
            await service.approve_payout_request(payout, admin, body.note)
        else:
            if not body.note:
                raise HTTPException(400, "A note is required when rejecting a payout")
            await service.reject_payout_request(payout, admin, body.note)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return await _payout_to_admin_read(payout)


@router.patch(
    "/admin/contributor/payout-requests/{payout_id}/mark-paid",
    response_model=PayoutRequestAdminRead,
    tags=["admin"],
)
async def mark_payout_paid(
    payout_id: uuid.UUID,
    admin: User = Depends(_require_admin),
) -> PayoutRequestAdminRead:
    from app.config import settings
    from app.core import paystack as paystack_client

    payout = await PayoutRequest.get_or_none(id=payout_id)
    if not payout:
        raise HTTPException(404, "Payout request not found")

    # If Paystack is live and payout is in approved state, initiate a real transfer.
    if settings.paystack_live and payout.status == PayoutRequestStatus.approved:
        bank = await ContributorBankAccount.get_or_none(contributor_id=payout.contributor_id)
        if bank and bank.paystack_recipient_code:
            reference = f"ptd-payout-{payout.id}"
            try:
                transfer_code = await paystack_client.initiate_transfer(
                    payout.requested_amount,
                    bank.paystack_recipient_code,
                    f"Prime Times Daily contributor payout",
                    reference,
                )
            except Exception as exc:
                raise HTTPException(502, f"Paystack transfer initiation failed: {exc}")
            await service.initiate_payout_transfer(payout, transfer_code)
            return await _payout_to_admin_read(payout)

    # Manual path: Paystack not configured, or account not Paystack-verified.
    try:
        await service.mark_payout_paid(payout, admin)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return await _payout_to_admin_read(payout)


# ══════════════════════════════════════════════════════════════════════════════
# CONTRIBUTOR — BANK LIST (live from Paystack, static fallback)
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/contributor/banks",
    tags=["contributor"],
)
async def list_banks(
    _user: User = Depends(_require_contributor),
) -> list[dict]:
    from app.core import paystack as paystack_client
    return await paystack_client.get_banks()


# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK — PAYSTACK
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/webhooks/paystack",
    status_code=200,
    tags=["webhooks"],
    include_in_schema=False,
)
async def paystack_webhook(request: Request) -> dict:
    """
    Handles Paystack transfer webhooks.
    Signature is verified with HMAC-SHA512 when PAYSTACK_WEBHOOK_SECRET is set.
    Always returns 200 — Paystack retries on non-2xx.
    """
    from app.config import settings
    from app.core import paystack as paystack_client

    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    if settings.PAYSTACK_WEBHOOK_SECRET and not paystack_client.verify_webhook_signature(raw_body, signature):
        # Return 200 even on bad signature so Paystack doesn't keep retrying with a stolen payload.
        return {"received": False, "reason": "invalid_signature"}

    try:
        payload = await request.json()
    except Exception:
        return {"received": False, "reason": "invalid_json"}

    event = payload.get("event", "")
    data = payload.get("data", {})
    transfer_code = data.get("transfer_code")

    if not transfer_code:
        return {"received": True}

    payout = await PayoutRequest.get_or_none(paystack_transfer_code=transfer_code)
    if not payout:
        return {"received": True}

    if event == "transfer.success":
        await service.complete_payout_paid(payout)

    elif event in ("transfer.failed", "transfer.reversed"):
        reason = data.get("reason") or data.get("gateway_response", "")
        await service.fail_payout(payout, reason or None)

    return {"received": True}


# ══════════════════════════════════════════════════════════════════════════════
# EDITOR — SET STORY PAY-WORTHY STATUS
# ══════════════════════════════════════════════════════════════════════════════

@router.patch(
    "/admin/stories/{story_id}/pay-worthy",
    tags=["editor", "admin"],
)
async def set_story_pay_worthy(
    story_id: uuid.UUID,
    body: StoryPayWorthyUpdate,
    editor: User = Depends(_require_editor),
) -> dict:
    story = await ConsoleStory.get_or_none(id=story_id)
    if not story:
        raise HTTPException(404, "Story not found")

    all_pass = (
        body.rubric.original_reporting
        and body.rubric.local_impact
        and body.rubric.public_interest
    )
    if body.is_pay_worthy and not all_pass:
        raise HTTPException(
            400,
            "All three rubric criteria (original_reporting, local_impact, "
            "public_interest) must be true to mark a story as pay-worthy.",
        )

    story.is_pay_worthy = body.is_pay_worthy and all_pass
    story.pay_worthy_rubric = body.rubric.model_dump()
    if body.editorial_score is not None:
        story.editorial_score = body.editorial_score
    await story.save()

    return {
        "story_id": str(story_id),
        "is_pay_worthy": story.is_pay_worthy,
        "editorial_score": story.editorial_score,
    }
