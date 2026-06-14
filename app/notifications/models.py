import enum
import uuid

from tortoise import fields
from tortoise.models import Model


class NotificationType(str, enum.Enum):
    # Story lifecycle
    story_submitted = "story_submitted"
    story_in_review = "story_in_review"
    story_published = "story_published"
    story_rejected = "story_rejected"
    story_note = "story_note"
    # Editor kicked a story back to the writer to fix something (with a note).
    story_changes_requested = "story_changes_requested"
    # A new comment was posted on the story's editorial thread.
    story_comment = "story_comment"
    # An editor edited the writer's story content directly.
    story_edited = "story_edited"
    # An editor assigned a story to a writer to write.
    story_assigned = "story_assigned"
    # Contributor application
    application_submitted = "application_submitted"
    application_under_review = "application_under_review"
    application_approved = "application_approved"
    application_rejected = "application_rejected"
    # Earnings
    earning_approved = "earning_approved"
    earning_rejected = "earning_rejected"
    earning_distributed = "earning_distributed"
    # Payouts
    payout_approved = "payout_approved"
    payout_rejected = "payout_rejected"
    payout_paid = "payout_paid"
    payout_failed = "payout_failed"
    # KYC
    kyc_submitted = "kyc_submitted"
    kyc_approved = "kyc_approved"
    kyc_rejected = "kyc_rejected"
    # Admin broadcast
    admin_message = "admin_message"


class Notification(Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    recipient = fields.ForeignKeyField("models.User", related_name="notifications")
    sender = fields.ForeignKeyField(
        "models.User", related_name="sent_notifications", null=True
    )
    notif_type = fields.CharEnumField(NotificationType, max_length=40)
    title = fields.CharField(max_length=200)
    body = fields.TextField(default="")
    link = fields.CharField(max_length=500, null=True)
    is_read = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "notifications"
        ordering = ["-created_at"]
