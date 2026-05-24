from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GatingPolicyRead(BaseModel):
    gating_start_date: datetime | None = None
    free_article_threshold: int
    day_pass_price_kobo: int
    week_pass_price_kobo: int
    is_active: bool = False

    model_config = ConfigDict(from_attributes=True)


class GatingPolicyUpdate(BaseModel):
    gating_start_date: datetime | None = None
    free_article_threshold: int | None = None
    day_pass_price_kobo: int | None = None
    week_pass_price_kobo: int | None = None


class GateStatusResponse(BaseModel):
    is_gated: bool
    is_premium: bool
    free_reads_used: int
    free_reads_allowed: int
    has_active_pass: bool
    pass_expires_at: datetime | None = None
    day_pass_price_kobo: int
    week_pass_price_kobo: int


class PurchasePassRequest(BaseModel):
    pass_type: str  # "day" or "week"


class PurchasePassResponse(BaseModel):
    pass_type: str
    expires_at: datetime
    day_pass_price_kobo: int
    week_pass_price_kobo: int
