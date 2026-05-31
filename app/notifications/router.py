import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from app.auth.dependencies import current_active_user
from app.auth.models import User
from app.core.roles import UserRole, role_has_at_least
from app.notifications.models import Notification, NotificationType
from app.notifications.schemas import AdminBroadcastCreate, NotificationList, NotificationRead
from app.notifications.service import create_notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _require_admin(user: User = Depends(current_active_user)) -> User:
    if not role_has_at_least(user.role, UserRole.admin):
        raise HTTPException(403, "Admin role required")
    return user


def _build_read(n: Notification, sender: User | None = None) -> NotificationRead:
    sender_name: str | None = None
    if sender is not None:
        sender_name = sender.display_name or sender.email
    return NotificationRead(
        id=n.id,
        notif_type=n.notif_type,
        title=n.title,
        body=n.body,
        link=n.link,
        is_read=n.is_read,
        created_at=n.created_at,
        sender_name=sender_name,
    )


async def _to_read(n: Notification) -> NotificationRead:
    """Single-notification read — lazily resolves sender (used by mark_read)."""
    sender: User | None = None
    if n.sender_id:
        try:
            sender = await n.sender
        except Exception:
            pass
    return _build_read(n, sender)


@router.get("", response_model=NotificationList)
async def list_notifications(
    unread_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(current_active_user),
) -> NotificationList:
    base_qs = Notification.filter(recipient_id=current_user.id)
    filtered_qs = base_qs.filter(is_read=False) if unread_only else base_qs

    total = await filtered_qs.count()
    unread_count = await base_qs.filter(is_read=False).count()
    rows = await filtered_qs.order_by("-created_at").offset(skip).limit(limit)

    # Batch-fetch all senders in one query to avoid N+1
    sender_ids = list({n.sender_id for n in rows if n.sender_id})
    sender_map: dict[str, User] = {}
    if sender_ids:
        senders = await User.filter(id__in=sender_ids)
        sender_map = {str(s.id): s for s in senders}

    return NotificationList(
        notifications=[_build_read(n, sender_map.get(str(n.sender_id))) for n in rows],
        total=total,
        unread_count=unread_count,
    )


@router.get("/unread-count")
async def unread_count(
    current_user: User = Depends(current_active_user),
) -> dict:
    count = await Notification.filter(recipient_id=current_user.id, is_read=False).count()
    return {"count": count}


@router.patch("/{notification_id}/read", response_model=NotificationRead)
async def mark_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(current_active_user),
) -> NotificationRead:
    n = await Notification.get_or_none(id=notification_id, recipient_id=current_user.id)
    if not n:
        raise HTTPException(404, "Notification not found")
    if not n.is_read:
        n.is_read = True
        await n.save()
    return await _to_read(n)


@router.post("/mark-all-read")
async def mark_all_read(
    current_user: User = Depends(current_active_user),
) -> dict:
    updated = await Notification.filter(
        recipient_id=current_user.id, is_read=False
    ).update(is_read=True)
    return {"marked_read": updated}


@router.delete("/{notification_id}", status_code=204)
async def delete_notification(
    notification_id: uuid.UUID,
    current_user: User = Depends(current_active_user),
) -> None:
    n = await Notification.get_or_none(id=notification_id, recipient_id=current_user.id)
    if not n:
        raise HTTPException(404, "Notification not found")
    await n.delete()


@router.get("/stream")
async def notification_stream(
    current_user: User = Depends(current_active_user),
) -> StreamingResponse:
    """SSE stream that pushes unread count when it changes. Replaces per-tab polling."""
    uid = current_user.id

    async def event_generator():
        last_count = -1
        try:
            while True:
                count = await Notification.filter(recipient_id=uid, is_read=False).count()
                if count != last_count:
                    yield f"data: {count}\n\n"
                    last_count = count
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/broadcast", status_code=201)
async def admin_broadcast(
    body: AdminBroadcastCreate,
    admin: User = Depends(_require_admin),
) -> dict:
    """Send an admin_message notification to specific users, specific roles, or all contributors."""
    if body.recipient_ids:
        ids = body.recipient_ids
    else:
        from app.auth.models import User as UserModel
        users = await UserModel.filter(is_active=True).all()
        if body.roles:
            target_roles = set(body.roles)
            ids = [u.id for u in users if u.role in target_roles and u.id != admin.id]
        else:
            ids = [
                u.id for u in users
                if role_has_at_least(u.role, UserRole.contributor) and u.id != admin.id
            ]

    count = 0
    for rid in ids:
        try:
            await create_notification(
                recipient_id=rid,
                notif_type=NotificationType.admin_message,
                title=body.title,
                body=body.body,
                link=body.link,
                sender_id=admin.id,
            )
            count += 1
        except Exception:
            pass

    return {"sent": count}
