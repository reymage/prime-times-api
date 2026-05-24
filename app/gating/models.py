import uuid

from tortoise import fields
from tortoise.models import Model


class GatingPolicy(Model):
    id = fields.IntField(pk=True)
    gating_start_date = fields.DatetimeField(null=True)
    free_article_threshold = fields.IntField(default=3)
    day_pass_price_kobo = fields.IntField(default=10000)    # ₦100
    week_pass_price_kobo = fields.IntField(default=40000)   # ₦400
    updated_at = fields.DatetimeField(auto_now=True)
    updated_by = fields.UUIDField(null=True)

    class Meta:
        table = "gating_policy"


class PremiumRead(Model):
    id = fields.IntField(pk=True)
    user: fields.ForeignKeyRelation = fields.ForeignKeyField(
        "models.User", related_name="premium_reads", on_delete=fields.CASCADE
    )
    article: fields.ForeignKeyRelation = fields.ForeignKeyField(
        "models.Article", related_name="premium_reads", on_delete=fields.CASCADE
    )
    read_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "premium_reads"
        unique_together = (("user", "article"),)


class PurchasedPass(Model):
    id = fields.IntField(pk=True)
    user: fields.ForeignKeyRelation = fields.ForeignKeyField(
        "models.User", related_name="purchased_passes", on_delete=fields.CASCADE
    )
    pass_type = fields.CharField(max_length=10)   # "day" or "week"
    purchased_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField()

    class Meta:
        table = "purchased_passes"
