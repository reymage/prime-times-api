import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Any

from pydantic import BaseModel, Field, field_validator

from app.contributors.models import (
    ApplicationStatus,
    EarningStatus,
    PayoutRequestStatus,
    PeriodStatus,
)


# ── Contributor application ───────────────────────────────────────────────────

class ApplicationSubmit(BaseModel):
    bio: str = Field(..., min_length=50, max_length=2000)
    portfolio_url: Optional[str] = Field(None, max_length=500)
    coverage_areas: list[str] = Field(..., min_length=1)
    verticals: list[str] = Field(..., min_length=1)
    kyc_document_type: Optional[str] = Field(None)
    kyc_document_ref: Optional[str] = Field(None, max_length=200)

    @field_validator("kyc_document_type")
    @classmethod
    def validate_kyc_type(cls, v: Optional[str]) -> Optional[str]:
        allowed = {"nin", "bvn", "passport", "drivers_license"}
        if v is not None and v not in allowed:
            raise ValueError(f"kyc_document_type must be one of {allowed}")
        return v


class ApplicationRead(BaseModel):
    id: uuid.UUID
    status: ApplicationStatus
    submitted_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewer_note: Optional[str] = None

    model_config = {"from_attributes": True}


class ApplicationAdminRead(BaseModel):
    id: uuid.UUID
    applicant_id: uuid.UUID
    applicant_email: str
    applicant_name: Optional[str]
    bio: str
    portfolio_url: Optional[str]
    coverage_areas: list
    verticals: list
    kyc_document_type: Optional[str]
    kyc_document_ref: Optional[str]
    status: ApplicationStatus
    submitted_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewer_note: Optional[str] = None

    model_config = {"from_attributes": True}


class ApplicationReview(BaseModel):
    status: ApplicationStatus  # approved | rejected
    reviewer_note: Optional[str] = Field(None, max_length=1000)


# ── Platform reward settings ──────────────────────────────────────────────────

class RewardSettingsRead(BaseModel):
    reward_start_date: Optional[date]
    contributor_revenue_share: Decimal
    updated_at: datetime

    model_config = {"from_attributes": True}


class RewardSettingsUpdate(BaseModel):
    reward_start_date: Optional[date] = None
    contributor_revenue_share: Optional[Decimal] = Field(
        None, ge=Decimal("0.01"), le=Decimal("1.00")
    )


# ── Contributor profile / eligibility ────────────────────────────────────────

class ContributorProfileRead(BaseModel):
    first_published_story_date: Optional[date]
    pay_worthy_eligible: bool
    eligibility_checked_at: Optional[datetime]
    eligibility_override: Optional[bool]
    eligibility_override_note: Optional[str]

    model_config = {"from_attributes": True}


class EligibilityOverrideUpdate(BaseModel):
    override: Optional[bool] = None      # None clears override back to algorithm
    note: Optional[str] = Field(None, max_length=500)


class EligibilityCriterion(BaseModel):
    pass_: bool = Field(..., alias="pass")
    value: Any
    required: Any

    model_config = {"populate_by_name": True}


class EligibilityBreakdown(BaseModel):
    eligible: bool
    override: Optional[bool]
    checked_at: Optional[datetime]
    reward_active: bool
    criteria: Optional[dict]


# ── Paywall revenue periods ───────────────────────────────────────────────────

class PeriodCreate(BaseModel):
    week_start: date
    week_end: date
    gross_paywall_revenue: Decimal = Field(..., ge=Decimal("0"))


class PeriodRead(BaseModel):
    id: uuid.UUID
    week_start: date
    week_end: date
    gross_paywall_revenue: Decimal
    revenue_share_pct: Decimal
    contributor_pool: Decimal
    status: PeriodStatus
    distributed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PeriodRevenueUpdate(BaseModel):
    gross_paywall_revenue: Decimal = Field(..., ge=Decimal("0"))


# ── Contributor earnings ──────────────────────────────────────────────────────

class EarningRead(BaseModel):
    id: uuid.UUID
    period_id: uuid.UUID
    week_start: date
    week_end: date
    paywall_reads: int
    pool_total_reads: int
    contributor_pool: Decimal
    share_pct: Decimal
    gross_amount: Decimal
    status: EarningStatus

    model_config = {"from_attributes": True}


class EarningsSummary(BaseModel):
    total_pending: Decimal
    total_approved: Decimal
    total_paid: Decimal
    earnings: list[EarningRead]


class EarningAdminRead(BaseModel):
    id: uuid.UUID
    contributor_id: uuid.UUID
    contributor_email: str
    contributor_name: Optional[str]
    period_id: uuid.UUID
    week_start: date
    week_end: date
    paywall_reads: int
    pool_total_reads: int
    contributor_pool: Decimal
    share_pct: Decimal
    gross_amount: Decimal
    status: EarningStatus

    model_config = {"from_attributes": True}


class EarningReview(BaseModel):
    status: EarningStatus  # approved | rejected
    note: Optional[str] = Field(None, max_length=500)


class BulkEarningApprove(BaseModel):
    period_id: uuid.UUID


# ── Pay-worthy story rubric ───────────────────────────────────────────────────

class PayWorthyRubric(BaseModel):
    original_reporting: bool
    local_impact: bool
    public_interest: bool


class StoryPayWorthyUpdate(BaseModel):
    is_pay_worthy: bool
    rubric: PayWorthyRubric
    editorial_score: Optional[int] = Field(None, ge=0, le=100)


# ── Bank account ─────────────────────────────────────────────────────────────

class BankAccountCreate(BaseModel):
    account_name: str = Field(..., min_length=2, max_length=200)
    bank_code: str = Field(..., min_length=2, max_length=20)
    bank_name: str = Field(..., min_length=2, max_length=200)
    account_number: str = Field(..., min_length=10, max_length=20)


class BankAccountRead(BaseModel):
    id: uuid.UUID
    account_name: str
    bank_code: str
    bank_name: str
    account_number_masked: str
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Payout requests ───────────────────────────────────────────────────────────

class PayoutRequestRead(BaseModel):
    id: uuid.UUID
    requested_amount: Decimal
    bank_account_snapshot: dict
    status: PayoutRequestStatus
    admin_note: Optional[str]
    approved_at: Optional[datetime]
    paid_at: Optional[datetime]
    created_at: datetime
    earnings_count: int

    model_config = {"from_attributes": True}


class PayoutRequestAdminRead(BaseModel):
    id: uuid.UUID
    contributor_id: uuid.UUID
    contributor_email: str
    contributor_name: Optional[str]
    requested_amount: Decimal
    bank_account_snapshot: dict
    status: PayoutRequestStatus
    admin_note: Optional[str]
    approved_at: Optional[datetime]
    paid_at: Optional[datetime]
    created_at: datetime
    earnings_count: int

    model_config = {"from_attributes": True}


class PayoutRequestReview(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    note: Optional[str] = Field(None, max_length=1000)
