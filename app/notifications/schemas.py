from datetime import datetime
import uuid

from pydantic import BaseModel

from app.notifications.models import NotificationType


class NotificationRead(BaseModel):
    id: uuid.UUID
    notif_type: NotificationType
    title: str
    body: str
    link: str | None
    is_read: bool
    created_at: datetime
    sender_name: str | None = None

    model_config = {"from_attributes": True}


class NotificationList(BaseModel):
    notifications: list[NotificationRead]
    total: int
    unread_count: int


class AdminBroadcastCreate(BaseModel):
    title: str
    body: str
    link: str | None = None
    # If roles is non-empty, send only to those roles; otherwise send to all >= contributor
    roles: list[str] = []
    # If recipient_ids is non-empty it takes precedence over roles
    recipient_ids: list[uuid.UUID] = []
