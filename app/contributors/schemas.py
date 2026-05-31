import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.contributors.models import (
    ApplicationStatus,
    EarningStatus,
    PayoutRequestStatus,
    PeriodStatus,
)


# ── Contributor application ───────────────────────────────────────────────────

class ApplicationSubmit(BaseModel):
    email: EmailStr
    # Step 1 — Identity
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    dob: str = Field(..., max_length=20)
    gender: str = Field(..., max_length=50)
    state_of_residence: str = Field(..., max_length=100)
    employment_status: str = Field(..., max_length=50)
    phone: str = Field(..., min_length=7, max_length=30)
    # Step 2 — Story & social
    bio: str = Field(..., min_length=50, max_length=300)
    portfolio_url: Optional[str] = Field(None, max_length=500)
    handle_x: Optional[str] = Field(None, max_length=100)
    handle_fb: Optional[str] = Field(None, max_length=300)
    handle_li: Optional[str] = Field(None, max_length=300)
    pitch: str = Field(..., min_length=10, max_length=280)
    # Step 3 — Work samples
    best_piece_url: str = Field(..., max_length=500)
    best_work_file_url: Optional[str] = Field(None, max_length=500)
    # Step 4 — Beat
    reporting_methods: list[str] = Field(..., min_length=1)
    primary_vertical: str = Field(..., max_length=100)
    secondary_vertical: Optional[str] = Field(None, max_length=100)

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: str) -> str:
        allowed = {"Male", "Female", "Non-binary", "Prefer not to say"}
        if v not in allowed:
            raise ValueError(f"gender must be one of {allowed}")
        return v

    @field_validator("employment_status")
    @classmethod
    def validate_employment_status(cls, v: str) -> str:
        allowed = {"Freelance", "Staff journalist", "Both"}
        if v not in allowed:
            raise ValueError(f"employment_status must be one of {allowed}")
        return v


class ApplicationRead(BaseModel):
    id: uuid.UUID
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: ApplicationStatus
    submitted_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewer_note: Optional[str] = None

    model_config = {"from_attributes": True}


class ApplicationAdminRead(BaseModel):
    id: uuid.UUID
    applicant_id: Optional[uuid.UUID] = None
    applicant_email: Optional[str] = None
    applicant_name: Optional[str]
    # Step 1
    first_name: Optional[str]
    last_name: Optional[str]
    dob: Optional[str]
    gender: Optional[str]
    state_of_residence: Optional[str]
    employment_status: Optional[str]
    phone: Optional[str]
    # Step 2
    bio: str
    portfolio_url: Optional[str]
    handle_x: Optional[str]
    handle_fb: Optional[str]
    handle_li: Optional[str]
    pitch: Optional[str]
    # Step 3
    best_piece_url: Optional[str]
    best_work_file_url: Optional[str]
    # Step 4
    reporting_methods: list
    primary_vertical: Optional[str]
    secondary_vertical: Optional[str]
    # Review
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
