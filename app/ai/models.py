import uuid

from tortoise import fields
from tortoise.models import Model


class AILog(Model):
    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    reporter_id = fields.CharField(max_length=255, db_index=True)
    endpoint = fields.CharField(max_length=20)          # suggest | generate
    story_type = fields.CharField(max_length=50, null=True)
    llm_provider = fields.CharField(max_length=30, null=True)
    llm_model = fields.CharField(max_length=100, null=True)
    llm_input_tokens = fields.IntField(default=0)
    llm_output_tokens = fields.IntField(default=0)
    llm_cost_usd = fields.DecimalField(max_digits=12, decimal_places=8, default=0)
    tavily_searches = fields.IntField(default=0)
    tavily_cost_usd = fields.DecimalField(max_digits=12, decimal_places=8, default=0)
    cache_hit = fields.BooleanField(default=False)
    attempts = fields.IntField(default=0)
    rewrites = fields.IntField(default=0)
    score = fields.IntField(null=True)
    success = fields.BooleanField(default=True)
    error_code = fields.CharField(max_length=50, null=True)
    duration_ms = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "ai_logs"
        ordering = ["-created_at"]
