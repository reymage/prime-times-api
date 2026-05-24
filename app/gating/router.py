from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.articles.models import Article
from app.auth.dependencies import current_active_user, fastapi_users
from app.auth.models import User
from app.core.roles import UserRole, require_role
from app.gating.models import GatingPolicy, PremiumRead, PurchasedPass
from app.gating.schemas import (
    GateStatusResponse,
    GatingPolicyRead,
    GatingPolicyUpdate,
    PurchasePassRequest,
    PurchasePassResponse,
)

router = APIRouter(prefix="/api/gating", tags=["gating"])

_optional_user = fastapi_users.current_user(active=True, optional=True)


async def _get_policy() -> GatingPolicy:
    policy = await GatingPolicy.filter().first()
    if not policy:
        policy = await GatingPolicy.create()
    return policy


def _gating_is_active(policy: GatingPolicy) -> bool:
    if not policy.gating_start_date:
        return False
    now = datetime.now(tz=timezone.utc)
    start = policy.gating_start_date
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return now >= start


@router.get("/policy", response_model=GatingPolicyRead)
async def get_gating_policy() -> GatingPolicyRead:
    policy = await _get_policy()
    data = GatingPolicyRead.model_validate(policy)
    data.is_active = _gating_is_active(policy)
    return data


@router.patch("/policy", response_model=GatingPolicyRead)
async def update_gating_policy(
    payload: GatingPolicyUpdate,
    current_user: User = Depends(require_role(UserRole.super_admin)),
) -> GatingPolicyRead:
    policy = await _get_policy()
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    policy.updated_by = current_user.id
    await policy.save()
    data = GatingPolicyRead.model_validate(policy)
    data.is_active = _gating_is_active(policy)
    return data


@router.get("/articles/{slug}/gate-status", response_model=GateStatusResponse)
async def get_gate_status(
    slug: str,
    current_user: User | None = Depends(_optional_user),
) -> GateStatusResponse:
    article = await Article.filter(slug=slug).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    policy = await _get_policy()
    is_active = _gating_is_active(policy)

    # No gating active or article is not premium — freely accessible
    if not is_active or not article.is_premium:
        return GateStatusResponse(
            is_gated=False,
            is_premium=article.is_premium,
            free_reads_used=0,
            free_reads_allowed=policy.free_article_threshold,
            has_active_pass=False,
            day_pass_price_kobo=policy.day_pass_price_kobo,
            week_pass_price_kobo=policy.week_pass_price_kobo,
        )

    # Unauthenticated readers are gated from premium articles
    if not current_user:
        return GateStatusResponse(
            is_gated=True,
            is_premium=True,
            free_reads_used=policy.free_article_threshold,
            free_reads_allowed=policy.free_article_threshold,
            has_active_pass=False,
            day_pass_price_kobo=policy.day_pass_price_kobo,
            week_pass_price_kobo=policy.week_pass_price_kobo,
        )

    now = datetime.now(tz=timezone.utc)

    # Check for an active purchased pass
    active_pass = (
        await PurchasedPass.filter(user_id=current_user.id, expires_at__gt=now)
        .order_by("-expires_at")
        .first()
    )
    if active_pass:
        return GateStatusResponse(
            is_gated=False,
            is_premium=True,
            free_reads_used=0,
            free_reads_allowed=policy.free_article_threshold,
            has_active_pass=True,
            pass_expires_at=active_pass.expires_at,
            day_pass_price_kobo=policy.day_pass_price_kobo,
            week_pass_price_kobo=policy.week_pass_price_kobo,
        )

    # Count how many distinct premium articles this user has read
    free_reads = await PremiumRead.filter(user_id=current_user.id).count()
    is_gated = free_reads >= policy.free_article_threshold

    # Record this read if still within the free threshold (idempotent via unique constraint)
    if not is_gated:
        await PremiumRead.get_or_create(user_id=current_user.id, article_id=article.id)
        free_reads = await PremiumRead.filter(user_id=current_user.id).count()

    return GateStatusResponse(
        is_gated=is_gated,
        is_premium=True,
        free_reads_used=free_reads,
        free_reads_allowed=policy.free_article_threshold,
        has_active_pass=False,
        day_pass_price_kobo=policy.day_pass_price_kobo,
        week_pass_price_kobo=policy.week_pass_price_kobo,
    )


@router.post("/purchase", response_model=PurchasePassResponse)
async def purchase_pass(
    payload: PurchasePassRequest,
    current_user: User = Depends(current_active_user),
) -> PurchasePassResponse:
    if payload.pass_type not in ("day", "week"):
        raise HTTPException(status_code=422, detail="pass_type must be 'day' or 'week'")

    policy = await _get_policy()
    now = datetime.now(tz=timezone.utc)

    if payload.pass_type == "day":
        expires_at = now.replace(hour=23, minute=59, second=59, microsecond=0)
    else:
        expires_at = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59, microsecond=0)

    await PurchasedPass.create(
        user_id=current_user.id,
        pass_type=payload.pass_type,
        expires_at=expires_at,
    )

    return PurchasePassResponse(
        pass_type=payload.pass_type,
        expires_at=expires_at,
        day_pass_price_kobo=policy.day_pass_price_kobo,
        week_pass_price_kobo=policy.week_pass_price_kobo,
    )
