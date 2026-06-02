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
import csv
import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.auth.dependencies import current_active_user
from app.auth.models import User
from app.console.models import ConsoleStory
from app.contributors.models import (
    ApplicationStatus,
    ContributorApplication,
    ContributorBankAccount,
    ContributorEarning,
    ContributorKYC,
    ContributorProfile,
    EarningStatus,
    KYCStatus,
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
    KYCAdminRead,
    KYCRead,
    KYCReview,
    KYCSubmit,
    OnboardingStatus,
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
from app.notifications.models import NotificationType
from app.notifications.service import create_notification as _notify
from app.ai.cache import cache_get, cache_set, cache_invalidate_prefix

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
) -> ContributorApplication:
    # Block if an active application already exists for this email.
    # Rejected applicants may re-apply (a new row is created).
    existing = await ContributorApplication.filter(
        email=body.email,
        status__in=[ApplicationStatus.pending, ApplicationStatus.under_review, ApplicationStatus.approved],
    ).first()
    if existing:
        raise HTTPException(409, "An application from this email address is already in progress or has been approved.")
    application = await ContributorApplication.create(
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        dob=body.dob,
        gender=body.gender,
        state_of_residence=body.state_of_residence,
        employment_status=body.employment_status,
        phone=body.phone,
        bio=body.bio,
        portfolio_url=body.portfolio_url,
        handle_x=body.handle_x,
        handle_fb=body.handle_fb,
        handle_li=body.handle_li,
        pitch=body.pitch,
        best_piece_url=body.best_piece_url,
        best_work_file_url=body.best_work_file_url,
        reporting_methods=body.reporting_methods,
        primary_vertical=body.primary_vertical,
        secondary_vertical=body.secondary_vertical,
    )
    # Notify all admins of the new application
    try:
        from app.auth.models import User as UserModel
        admins = await UserModel.filter(is_active=True).values_list("id", "role")
        name = f"{body.first_name} {body.last_name}".strip() or body.email
        for admin_id, role in admins:
            if role_has_at_least(role, UserRole.admin):
                await _notify(
                    recipient_id=admin_id,
                    notif_type=NotificationType.application_submitted,
                    title="New contributor application",
                    body=f"{name} has submitted a contributor application.",
                    link="/console/admin/applications",
                    sender_id=None,
                )
    except Exception:
        pass
    return application


@router.post(
    "/contributor/upload-best-work",
    tags=["contributor"],
)
async def upload_best_work(
    file: UploadFile = File(...),
) -> dict:
    from app.storage import ALLOWED_DOCUMENT_MIME_TYPES, MAX_DOCUMENT_BYTES, upload_document_to_r2, is_r2_configured

    if file.content_type not in ALLOWED_DOCUMENT_MIME_TYPES:
        raise HTTPException(415, "Only PDF or DOCX files are accepted")

    data = await file.read()
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "File must be under 10 MB")

    if not is_r2_configured():
        raise HTTPException(503, "File storage is not configured")

    url = await upload_document_to_r2(data, file.content_type, folder="applications")
    return {"url": url}


@router.get(
    "/contributor/application/lookup",
    response_model=ApplicationRead,
    tags=["contributor"],
)
async def lookup_application(
    email: str = Query(...),
) -> ContributorApplication:
    """Public endpoint — look up an application by the applicant's email address."""
    app = (
        await ContributorApplication.filter(email=email)
        .order_by("-submitted_at")
        .first()
    )
    if not app:
        raise HTTPException(404, "No application found for this email address")
    return app


# ══════════════════════════════════════════════════════════════════════════════
# CONTRIBUTOR — ONBOARDING STATUS
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/contributor/onboarding-status",
    response_model=OnboardingStatus,
    tags=["contributor"],
)
async def get_onboarding_status(
    current_user: User = Depends(current_active_user),
) -> OnboardingStatus:
    """Returns whether this user has an approved application and their current KYC status.
    Accessible to any logged-in user regardless of role."""
    profile = await ContributorProfile.get_or_none(contributor_id=current_user.id)
    if not profile:
        return OnboardingStatus(application_approved=False, kyc_status=None)
    kyc = await ContributorKYC.get_or_none(contributor_id=current_user.id)
    return OnboardingStatus(
        application_approved=True,
        kyc_status=kyc.status.value if kyc else None,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CONTRIBUTOR — KYC
# ══════════════════════════════════════════════════════════════════════════════

def _require_approved_applicant(user: User = Depends(current_active_user)) -> User:
    """Allows any logged-in user who has an approved application (ContributorProfile).
    Does NOT require contributor role — this gate is for pre-KYC applicants."""
    return user  # Profile check done inside handlers to avoid async in depends


@router.post(
    "/contributor/kyc/upload",
    tags=["contributor"],
)
async def upload_kyc_document(
    file: UploadFile = File(...),
    _user: User = Depends(current_active_user),
) -> dict:
    """Upload a KYC identity document image or PDF. Returns a CDN URL."""
    from app.storage import upload_to_r2, upload_document_to_r2, is_r2_configured

    ALLOWED_KYC_TYPES = {
        "image/jpeg", "image/png", "image/webp",
        "application/pdf",
    }
    MAX_KYC_BYTES = 10 * 1024 * 1024  # 10 MB

    if file.content_type not in ALLOWED_KYC_TYPES:
        raise HTTPException(415, "Only JPEG, PNG, WebP, or PDF files are accepted")

    data = await file.read()
    if len(data) > MAX_KYC_BYTES:
        raise HTTPException(413, "File must be under 10 MB")

    if not is_r2_configured():
        raise HTTPException(503, "File storage is not configured")

    if file.content_type == "application/pdf":
        url = await upload_document_to_r2(data, file.content_type, folder="kyc")
    else:
        url = await upload_to_r2(data, file.content_type, folder="kyc")
    return {"url": url}


@router.post(
    "/contributor/kyc",
    response_model=KYCRead,
    status_code=201,
    tags=["contributor"],
)
async def submit_kyc(
    body: KYCSubmit,
    current_user: User = Depends(current_active_user),
) -> KYCRead:
    """Submit identity verification. Requires an approved contributor application."""
    profile = await ContributorProfile.get_or_none(contributor_id=current_user.id)
    if not profile:
        raise HTTPException(403, "No approved contributor application found for this account")

    existing = await ContributorKYC.get_or_none(contributor_id=current_user.id)
    if existing and existing.status == KYCStatus.approved:
        raise HTTPException(409, "Identity already verified")
    if existing and existing.status == KYCStatus.pending:
        raise HTTPException(409, "A verification submission is already under review")

    if existing:
        # Resubmission after rejection — update in place
        existing.full_name = body.full_name
        existing.nin_or_bvn = body.nin_or_bvn
        existing.document_type = body.document_type
        existing.document_url = body.document_url
        existing.status = KYCStatus.pending
        existing.reviewer_note = None
        existing.reviewed_at = None
        existing.reviewed_by_id = None
        await existing.save()
        kyc = existing
    else:
        kyc = await ContributorKYC.create(
            contributor_id=current_user.id,
            full_name=body.full_name,
            nin_or_bvn=body.nin_or_bvn,
            document_type=body.document_type,
            document_url=body.document_url,
        )

    # Notify admins
    try:
        from app.auth.models import User as UserModel
        admins = await UserModel.filter(is_active=True).values_list("id", "role")
        for admin_id, role in admins:
            if role_has_at_least(role, UserRole.admin):
                await _notify(
                    recipient_id=admin_id,
                    notif_type=NotificationType.kyc_submitted,
                    title="New KYC submission",
                    body=f"{current_user.display_name or current_user.email} has submitted identity verification documents.",
                    link="/console/admin/kyc",
                    sender_id=None,
                )
    except Exception:
        pass

    return KYCRead(
        id=kyc.id,
        status=kyc.status,
        full_name=kyc.full_name,
        document_type=kyc.document_type,
        submitted_at=kyc.submitted_at,
        reviewed_at=kyc.reviewed_at,
        reviewer_note=kyc.reviewer_note,
    )


@router.get(
    "/contributor/kyc",
    response_model=KYCRead,
    tags=["contributor"],
)
async def get_my_kyc(
    current_user: User = Depends(current_active_user),
) -> KYCRead:
    kyc = await ContributorKYC.get_or_none(contributor_id=current_user.id)
    if not kyc:
        raise HTTPException(404, "No KYC submission found")
    return KYCRead(
        id=kyc.id,
        status=kyc.status,
        full_name=kyc.full_name,
        document_type=kyc.document_type,
        submitted_at=kyc.submitted_at,
        reviewed_at=kyc.reviewed_at,
        reviewer_note=kyc.reviewer_note,
    )


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
    cache_key = f"eligibility:{current_user.id}"
    cached = await cache_get(cache_key)
    if cached:
        return EligibilityBreakdown(**cached)
    breakdown = await service.get_eligibility_breakdown(current_user)
    result = EligibilityBreakdown(**breakdown)
    await cache_set(cache_key, result.model_dump(mode="json"), ttl=120)
    return result


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
    cache_key = f"earnings:{current_user.id}"
    cached = await cache_get(cache_key)
    if cached:
        return EarningsSummary(**cached)

    raw = await ContributorEarning.filter(
        contributor_id=current_user.id
    ).prefetch_related("period").order_by("-created_at")

    total_pending = sum(e.gross_amount for e in raw if e.status == EarningStatus.pending)
    total_approved = sum(e.gross_amount for e in raw if e.status == EarningStatus.approved)
    total_paid = sum(e.gross_amount for e in raw if e.status == EarningStatus.paid)

    earnings = [_earning_to_read(e, await e.period) for e in raw]

    summary = EarningsSummary(
        total_pending=total_pending or Decimal("0"),
        total_approved=total_approved or Decimal("0"),
        total_paid=total_paid or Decimal("0"),
        earnings=earnings,
    )
    await cache_set(cache_key, summary.model_dump(mode="json"), ttl=90)
    return summary


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

def _app_to_admin_read(a: ContributorApplication, applicant) -> ApplicationAdminRead:
    return ApplicationAdminRead(
        id=a.id,
        applicant_id=applicant.id if applicant else None,
        applicant_email=(applicant.email if applicant else None) or a.email,
        applicant_name=(applicant.display_name if applicant else None) or (
            f"{a.first_name or ''} {a.last_name or ''}".strip() or None
        ),
        first_name=a.first_name,
        last_name=a.last_name,
        dob=a.dob,
        gender=a.gender,
        state_of_residence=a.state_of_residence,
        employment_status=a.employment_status,
        phone=a.phone,
        bio=a.bio,
        portfolio_url=a.portfolio_url,
        handle_x=a.handle_x,
        handle_fb=a.handle_fb,
        handle_li=a.handle_li,
        pitch=a.pitch,
        best_piece_url=a.best_piece_url,
        best_work_file_url=a.best_work_file_url,
        reporting_methods=a.reporting_methods or [],
        primary_vertical=a.primary_vertical,
        secondary_vertical=a.secondary_vertical,
        status=a.status,
        submitted_at=a.submitted_at,
        reviewed_at=a.reviewed_at,
        reviewer_note=a.reviewer_note,
    )


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
        applicant = (await a.applicant) if a.applicant_id else None
        result.append(_app_to_admin_read(a, applicant))
    return result


@router.get(
    "/admin/contributor/applications/export",
    tags=["admin"],
)
async def export_applications(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    _admin: User = Depends(_require_admin),
) -> StreamingResponse:
    """Export applications as CSV, optionally filtered by submission date range."""
    qs = ContributorApplication.all()
    if from_date:
        qs = qs.filter(submitted_at__gte=datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc))
    if to_date:
        qs = qs.filter(submitted_at__lte=datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc))
    apps = await qs.order_by("submitted_at")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Reference", "Submitted At", "Status",
        "First Name", "Last Name", "Email", "DOB", "Gender", "State", "Employment", "Phone",
        "Bio", "Pitch", "Portfolio URL", "Handle X", "Handle FB", "Handle LinkedIn",
        "Best Piece URL", "Has Uploaded File",
        "Primary Vertical", "Secondary Vertical", "Reporting Methods",
        "Reviewer Note",
    ])
    for a in apps:
        applicant = (await a.applicant) if a.applicant_id else None
        ref = f"PTD-{a.submitted_at.year}-{str(a.id).replace('-', '')[:5].upper()}"
        writer.writerow([
            ref,
            a.submitted_at.strftime("%Y-%m-%d %H:%M"),
            a.status.value,
            a.first_name or "",
            a.last_name or "",
            (applicant.email if applicant else None) or a.email or "",
            a.dob or "",
            a.gender or "",
            a.state_of_residence or "",
            a.employment_status or "",
            a.phone or "",
            a.bio,
            a.pitch or "",
            a.portfolio_url or "",
            a.handle_x or "",
            a.handle_fb or "",
            a.handle_li or "",
            a.best_piece_url or "",
            "Yes" if a.best_work_file_url else "No",
            a.primary_vertical or "",
            a.secondary_vertical or "",
            ", ".join(a.reporting_methods or []),
            a.reviewer_note or "",
        ])
    output.seek(0)
    today = date.today().isoformat()
    filename = f"applications_export_{today}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    if body.status == ApplicationStatus.under_review:
        if app.status != ApplicationStatus.pending:
            raise HTTPException(409, "Only pending applications can be moved to editorial review")
        app.status = ApplicationStatus.under_review
        await app.save()
        # Only send in-app notification if applicant has a user account
        if app.applicant_id:
            try:
                applicant = await app.applicant
                await _notify(
                    recipient_id=applicant.id,
                    notif_type=NotificationType.application_under_review,
                    title="Your application is under review",
                    body="Our editorial team has started reviewing your contributor application. You'll hear from us soon.",
                    link="/auth/contributor-status",
                    sender_id=admin.id,
                )
            except Exception:
                pass

    elif body.status == ApplicationStatus.approved:
        if app.status not in (ApplicationStatus.pending, ApplicationStatus.under_review):
            raise HTTPException(409, "Application has already been decided")
        await service.approve_application(app, admin, body.reviewer_note)
        # approve_application may have created and linked a user account — reload
        if app.applicant_id:
            try:
                applicant = await app.applicant
                await _notify(
                    recipient_id=applicant.id,
                    notif_type=NotificationType.application_approved,
                    title="Your contributor application was approved",
                    body="Welcome to the Prime Times Daily contributor programme. You can now submit stories.",
                    link="/console",
                    sender_id=admin.id,
                )
            except Exception:
                pass

    elif body.status == ApplicationStatus.rejected:
        if app.status not in (ApplicationStatus.pending, ApplicationStatus.under_review):
            raise HTTPException(409, "Application has already been decided")
        await service.reject_application(app, admin, body.reviewer_note)
        if app.applicant_id:
            try:
                applicant = await app.applicant
                note_preview = f" Reviewer note: {body.reviewer_note}" if body.reviewer_note else ""
                await _notify(
                    recipient_id=applicant.id,
                    notif_type=NotificationType.application_rejected,
                    title="Your contributor application was not approved",
                    body=f"Unfortunately your application was not approved at this time.{note_preview}",
                    link="/console",
                    sender_id=admin.id,
                )
            except Exception:
                pass

    else:
        raise HTTPException(400, "status must be 'under_review', 'approved', or 'rejected'")

    applicant = (await app.applicant) if app.applicant_id else None
    return _app_to_admin_read(app, applicant)


@router.get(
    "/admin/contributor/applications/{application_id}/download",
    tags=["admin"],
)
async def download_application(
    application_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
) -> PlainTextResponse:
    """Download a single application as a plain-text summary file."""
    app = await ContributorApplication.get_or_none(id=application_id)
    if not app:
        raise HTTPException(404, "Application not found")
    applicant = (await app.applicant) if app.applicant_id else None
    ref = f"PTD-{app.submitted_at.year}-{str(app.id).replace('-', '')[:5].upper()}"
    display_email = (applicant.email if applicant else None) or app.email or "—"

    lines = [
        "PRIME TIMES DAILY — CONTRIBUTOR APPLICATION",
        f"Reference:  {ref}",
        f"Submitted:  {app.submitted_at.strftime('%d %B %Y, %H:%M UTC')}",
        f"Status:     {app.status.value.upper()}",
        "",
        "── IDENTITY ──────────────────────────────────",
        f"Name:       {(app.first_name or '')} {(app.last_name or '')}".strip(),
        f"Email:      {display_email}",
        f"DOB:        {app.dob or '—'}",
        f"Gender:     {app.gender or '—'}",
        f"State:      {app.state_of_residence or '—'}",
        f"Employment: {app.employment_status or '—'}",
        f"Phone:      {app.phone or '—'}",
        "",
        "── STORY ─────────────────────────────────────",
        f"Bio:\n  {app.bio}",
        f"Pitch:     {app.pitch or '—'}",
        f"Portfolio: {app.portfolio_url or '—'}",
        f"X:         {app.handle_x or '—'}",
        f"Facebook:  {app.handle_fb or '—'}",
        f"LinkedIn:  {app.handle_li or '—'}",
        "",
        "── WORK SAMPLES ──────────────────────────────",
        f"Best piece: {app.best_piece_url or '—'}",
        f"Uploaded:   {app.best_work_file_url or '—'}",
        "",
        "── BEAT ──────────────────────────────────────",
        f"Primary vertical:    {app.primary_vertical or '—'}",
        f"Secondary vertical:  {app.secondary_vertical or '—'}",
        f"Reporting methods:   {', '.join(app.reporting_methods or []) or '—'}",
    ]
    if app.reviewer_note:
        lines += ["", "── REVIEWER NOTE ─────────────────────────────", app.reviewer_note]

    content = "\n".join(lines)
    filename = f"application_{ref}.txt"
    return PlainTextResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/admin/contributor/applications/{application_id}",
    status_code=204,
    tags=["admin"],
)
async def delete_application(
    application_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
) -> None:
    deleted = await ContributorApplication.filter(id=application_id).delete()
    if not deleted:
        raise HTTPException(404, "Application not found")


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — KYC
# ══════════════════════════════════════════════════════════════════════════════

async def _kyc_to_admin_read(kyc: ContributorKYC) -> KYCAdminRead:
    contributor = await kyc.contributor
    return KYCAdminRead(
        id=kyc.id,
        contributor_id=contributor.id,
        contributor_email=contributor.email,
        contributor_name=contributor.display_name,
        status=kyc.status,
        full_name=kyc.full_name,
        nin_or_bvn=kyc.nin_or_bvn,
        document_type=kyc.document_type,
        document_url=kyc.document_url,
        submitted_at=kyc.submitted_at,
        reviewed_at=kyc.reviewed_at,
        reviewer_note=kyc.reviewer_note,
    )


@router.get(
    "/admin/contributor/kyc",
    response_model=list[KYCAdminRead],
    tags=["admin"],
)
async def list_kyc_submissions(
    status: Optional[KYCStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(_require_admin),
) -> list[KYCAdminRead]:
    qs = ContributorKYC.all().order_by("-submitted_at")
    if status:
        qs = qs.filter(status=status)
    submissions = await qs.offset(skip).limit(limit)
    return [await _kyc_to_admin_read(k) for k in submissions]


@router.post(
    "/admin/contributor/kyc/{user_id}/approve",
    response_model=KYCAdminRead,
    tags=["admin"],
)
async def approve_kyc_submission(
    user_id: uuid.UUID,
    admin: User = Depends(_require_admin),
) -> KYCAdminRead:
    kyc = await ContributorKYC.get_or_none(contributor_id=user_id)
    if not kyc:
        raise HTTPException(404, "No KYC submission found for this user")
    if kyc.status == KYCStatus.approved:
        raise HTTPException(409, "Already approved")

    await service.approve_kyc(kyc, admin)

    try:
        contributor = await kyc.contributor
        await _notify(
            recipient_id=contributor.id,
            notif_type=NotificationType.kyc_approved,
            title="Identity verified",
            body="Your identity verification has been approved. You now have full access to the contributor console.",
            link="/console",
            sender_id=admin.id,
        )
    except Exception:
        pass

    return await _kyc_to_admin_read(kyc)


@router.post(
    "/admin/contributor/kyc/{user_id}/reject",
    response_model=KYCAdminRead,
    tags=["admin"],
)
async def reject_kyc_submission(
    user_id: uuid.UUID,
    body: KYCReview,
    admin: User = Depends(_require_admin),
) -> KYCAdminRead:
    kyc = await ContributorKYC.get_or_none(contributor_id=user_id)
    if not kyc:
        raise HTTPException(404, "No KYC submission found for this user")
    if kyc.status == KYCStatus.approved:
        raise HTTPException(409, "Cannot reject an already approved KYC")

    await service.reject_kyc(kyc, admin, body.note)

    try:
        contributor = await kyc.contributor
        await _notify(
            recipient_id=contributor.id,
            notif_type=NotificationType.kyc_rejected,
            title="Identity verification not approved",
            body=f"Your verification documents could not be confirmed. Please resubmit.{' Note: ' + body.note if body.note else ''}",
            link="/auth/contributor-kyc",
            sender_id=admin.id,
        )
    except Exception:
        pass

    return await _kyc_to_admin_read(kyc)


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
    try:
        amount_str = f"₦{float(earning.gross_amount):,.2f}"
        if body.status == EarningStatus.approved:
            await _notify(
                recipient_id=contributor.id,
                notif_type=NotificationType.earning_approved,
                title="Earning approved",
                body=f"{amount_str} earning from the period {period.week_start.date()} – {period.week_end.date()} has been approved.",
                link="/console/earnings",
                sender_id=admin.id,
            )
        else:
            await _notify(
                recipient_id=contributor.id,
                notif_type=NotificationType.earning_rejected,
                title="Earning not approved",
                body=f"An earning of {amount_str} was not approved. Note: {body.note or '—'}",
                link="/console/earnings",
                sender_id=admin.id,
            )
    except Exception:
        pass

    await cache_invalidate_prefix(f"earnings:{contributor.id}")
    await cache_invalidate_prefix(f"eligibility:{contributor.id}")
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

    # Send one consolidated email + in-app notification per contributor.
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
            try:
                await _notify(
                    recipient_id=user.id,
                    notif_type=NotificationType.earning_approved,
                    title="Earnings approved",
                    body=f"₦{float(total):,.2f} in earnings for this period have been approved. You can now request a payout.",
                    link="/console/earnings",
                    sender_id=admin.id,
                )
            except Exception:
                pass

    # Bust cached earnings for everyone whose earnings changed
    for cid_str in approved_by_contributor:
        await cache_invalidate_prefix(f"earnings:{cid_str}")
        await cache_invalidate_prefix(f"eligibility:{cid_str}")
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

    try:
        contributor = await payout.contributor
        amount_str = f"₦{float(payout.requested_amount):,.2f}"
        if body.action == "approve":
            await _notify(
                recipient_id=contributor.id,
                notif_type=NotificationType.payout_approved,
                title="Payout request approved",
                body=f"Your payout request of {amount_str} has been approved and will be processed shortly.",
                link="/console/payout-requests",
                sender_id=admin.id,
            )
        else:
            await _notify(
                recipient_id=contributor.id,
                notif_type=NotificationType.payout_rejected,
                title="Payout request not approved",
                body=f"Your payout request of {amount_str} was not approved. Reason: {body.note}",
                link="/console/payout-requests",
                sender_id=admin.id,
            )
    except Exception:
        pass

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
