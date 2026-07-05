import enum

from tortoise import fields
from tortoise.models import Model


class ContactReason(str, enum.Enum):
    advertising = "advertising"
    business = "business"
    news_tip = "news_tip"
    press = "press"
    careers = "careers"
    feedback = "feedback"
    other = "other"


class ContactMessage(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=200)
    email = fields.CharField(max_length=320)
    organisation = fields.CharField(max_length=200, null=True)
    reason = fields.CharEnumField(ContactReason, default=ContactReason.other, max_length=30)
    subject = fields.CharField(max_length=300, default="")
    message = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "contact_messages"
        ordering = ["-created_at"]
