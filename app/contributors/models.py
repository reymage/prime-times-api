import enum
import uuid

from tortoise import fields
from tortoise.models import Model


class ApplicationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class EarningStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    paid = "paid"
    rejected = "rejected"


class PeriodStatus(str, enum.Enum):
    open = "open"
    closed = "closed"
    distributed = "distributed"


class PayoutRequestStatus(str, enum.Enum):
    pending_admin = "pending_admin"
    approved = "approved"
    processing = "processing"
    paid = "paid"
    rejected = "rejected"
    failed = "failed"


class PlatformRewardSettings(Model):
    """Single-row table. Seed one row on first run; always update that row."""
    id = fields.IntField(pk=True)
    # Null = rewards permanently disabled until admin sets a date.
    reward_start_date = fields.DateField(null=True)
    # Fraction of weekly paywall revenue that goes to the contributor pool.
    contributor_revenue_share = fields.DecimalField(
        max_digits=5, decimal_places=4, default="0.6000"
    )
    updated_by = fields.ForeignKeyField(
        "models.User", related_name="reward_setting_updates", null=True, on_delete=fields.SET_NULL
    )
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "platform_reward_settings"


class ContributorApplication(Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    applicant = fields.ForeignKeyField(
        "models.User", related_name="contributor_applications", on_delete=fields.CASCADE
    )
    # Step 1 — Identity
    first_name = fields.CharField(max_length=100, null=True)
    last_name = fields.CharField(max_length=100, null=True)
    dob = fields.CharField(max_length=20, null=True)
    gender = fields.CharField(max_length=50, null=True)
    state_of_residence = fields.CharField(max_length=100, null=True)
    employment_status = fields.CharField(max_length=50, null=True)
    phone = fields.CharField(max_length=30, null=True)
    # Step 2 — Story & social
    bio = fields.TextField()
    portfolio_url = fields.CharField(max_length=500, null=True)
    handle_x = fields.CharField(max_length=100, null=True)
    handle_fb = fields.CharField(max_length=300, null=True)
    handle_li = fields.CharField(max_length=300, null=True)
    pitch = fields.CharField(max_length=280, null=True)
    # Step 3 — Work samples
    best_piece_url = fields.CharField(max_length=500, null=True)
    best_work_file_url = fields.CharField(max_length=500, null=True)
    # Step 4 — Beat
    reporting_methods = fields.JSONField(default=list)
    primary_vertical = fields.CharField(max_length=100, null=True)
    secondary_vertical = fields.CharField(max_length=100, null=True)
    # Legacy fields preserved for existing records
    coverage_areas = fields.JSONField(default=list)
    verticals = fields.JSONField(default=list)
    kyc_document_type = fields.CharField(max_length=50, null=True)
    kyc_document_ref = fields.CharField(max_length=200, null=True)
    # Review state
    status = fields.CharEnumField(
        ApplicationStatus, default=ApplicationStatus.pending, max_length=20
    )
    reviewer = fields.ForeignKeyField(
        "models.User", related_name="reviewed_applications", null=True, on_delete=fields.SET_NULL
    )
    reviewer_note = fields.TextField(null=True)
    reviewed_at = fields.DatetimeField(null=True)
    submitted_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "contributor_applications"
        ordering = ["-submitted_at"]


class ContributorProfile(Model):
    """Created automatically when an application is approved."""
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    contributor = fields.OneToOneField(
        "models.User", related_name="contributor_profile", on_delete=fields.CASCADE
    )
    # Set when their first story status transitions to 'publish'.
    first_published_story_date = fields.DateField(null=True)
    # Algorithm-computed eligibility (refreshed on each evaluation run).
    pay_worthy_eligible = fields.BooleanField(default=False)
    eligibility_checked_at = fields.DatetimeField(null=True)
    # Editorial override: None = use algorithm result; True/False = hard override.
    eligibility_override = fields.BooleanField(null=True)
    eligibility_override_by = fields.ForeignKeyField(
        "models.User", related_name="eligibility_overrides", null=True, on_delete=fields.SET_NULL
    )
    eligibility_override_at = fields.DatetimeField(null=True)
    eligibility_override_note = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "contributor_profiles"


class PaywallRevenuePeriod(Model):
    """
    One row per weekly distribution window.
    ONLY paywall income goes here — ad/sponsorship revenue must never be added.
    Admin creates and closes periods manually (or via scheduled job in a later phase).
    """
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    week_start = fields.DateField()
    week_end = fields.DateField()
    # Gross paywall income collected this week (₦).
    gross_paywall_revenue = fields.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    # Snapshot of the share % at distribution time.
    revenue_share_pct = fields.DecimalField(max_digits=5, decimal_places=4, default="0.6000")
    # = gross_paywall_revenue * revenue_share_pct; computed at distribution time.
    contributor_pool = fields.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    status = fields.CharEnumField(PeriodStatus, default=PeriodStatus.open, max_length=20)
    distributed_at = fields.DatetimeField(null=True)
    distributed_by = fields.ForeignKeyField(
        "models.User", related_name="distributed_periods", null=True, on_delete=fields.SET_NULL
    )
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "paywall_revenue_periods"
        ordering = ["-week_start"]


class ContributorEarning(Model):
    """
    One row per contributor per period. Created during the distribution run.
    Status starts pending; admin approves before payout (handled in phase 3/4).
    """
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    contributor = fields.ForeignKeyField(
        "models.User", related_name="earnings", on_delete=fields.CASCADE
    )
    period = fields.ForeignKeyField(
        "models.PaywallRevenuePeriod", related_name="earnings", on_delete=fields.CASCADE
    )
    # Sum of paywall_read_count for this contributor's pay-worthy stories in this period.
    paywall_reads = fields.IntField(default=0)
    # Total paywall reads across ALL eligible contributors this period (for pro-rata calc).
    pool_total_reads = fields.IntField(default=0)
    # contributor_pool * (paywall_reads / pool_total_reads)
    gross_amount = fields.DecimalField(max_digits=14, decimal_places=2, default="0.00")
    status = fields.CharEnumField(EarningStatus, default=EarningStatus.pending, max_length=20)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "contributor_earnings"
        ordering = ["-created_at"]
        unique_together = (("contributor", "period"),)


class PaywallReadEvent(Model):
    """
    One row per unique reader per ConsoleStory paywall unlock.
    Created when a reader with a valid pass (or still within free reads) accesses
    a pay-worthy story. Used as the authoritative read source for distribution.
    """
    id = fields.IntField(pk=True)
    console_story = fields.ForeignKeyField(
        "models.ConsoleStory", related_name="paywall_read_events", on_delete=fields.CASCADE
    )
    reader = fields.ForeignKeyField(
        "models.User", related_name="paywall_read_events", on_delete=fields.CASCADE
    )
    read_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "paywall_read_events"
        unique_together = (("console_story", "reader"),)
        ordering = ["-read_at"]


class ContributorBankAccount(Model):
    """One bank account per contributor. Replaced (delete + create) on update."""
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    contributor = fields.OneToOneField(
        "models.User", related_name="bank_account", on_delete=fields.CASCADE
    )
    account_name = fields.CharField(max_length=200)
    bank_code = fields.CharField(max_length=20)
    bank_name = fields.CharField(max_length=200)
    account_number = fields.CharField(max_length=20)
    is_verified = fields.BooleanField(default=False)
    # Populated by Paystack account resolution on save. Null = not yet verified via Paystack.
    paystack_recipient_code = fields.CharField(max_length=100, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "contributor_bank_accounts"


class PayoutRequest(Model):
    """
    Contributor-initiated payout claim against their approved earnings.
    Admin approves → marks paid (or rejects/fails).
    """
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    contributor = fields.ForeignKeyField(
        "models.User", related_name="payout_requests", on_delete=fields.CASCADE
    )
    requested_amount = fields.DecimalField(max_digits=14, decimal_places=2)
    # Snapshot of bank details at request time so history is preserved if account changes.
    bank_account_snapshot = fields.JSONField()
    status = fields.CharEnumField(
        PayoutRequestStatus, default=PayoutRequestStatus.pending_admin, max_length=20
    )
    admin_note = fields.TextField(null=True)
    approved_by = fields.ForeignKeyField(
        "models.User", related_name="approved_payout_requests", null=True, on_delete=fields.SET_NULL
    )
    approved_at = fields.DatetimeField(null=True)
    paid_at = fields.DatetimeField(null=True)
    # Paystack transfer tracking — null when transfer not yet initiated or Paystack disabled.
    paystack_transfer_code = fields.CharField(max_length=100, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "payout_requests"
        ordering = ["-created_at"]


class PayoutRequestEarning(Model):
    """Junction: which ContributorEarning rows are included in a PayoutRequest."""
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    payout_request = fields.ForeignKeyField(
        "models.PayoutRequest", related_name="request_earnings", on_delete=fields.CASCADE
    )
    earning = fields.ForeignKeyField(
        "models.ContributorEarning", related_name="payout_links", on_delete=fields.CASCADE
    )

    class Meta:
        table = "payout_request_earnings"
        unique_together = (("payout_request", "earning"),)
