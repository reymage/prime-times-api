"""
Notification service — thin helper called by other routers to fire notifications.
All calls are fire-and-forget; callers wrap them in try/except so a notification
failure never breaks the primary operation.
"""
import uuid

from app.notifications.models import Notification, NotificationType


async def create_notification(
    recipient_id: uuid.UUID,
    notif_type: NotificationType,
    title: str,
    body: str = "",
    link: str | None = None,
    sender_id: uuid.UUID | None = None,
) -> Notification:
    return await Notification.create(
        recipient_id=recipient_id,
        sender_id=sender_id,
        notif_type=notif_type,
        title=title,
        body=body,
        link=link,
    )
