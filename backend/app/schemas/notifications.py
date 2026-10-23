import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.notification import NotificationChannel, NotificationEvent, NotificationStatus


class NotificationOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    event_type: NotificationEvent
    title: str
    body: str
    channel: NotificationChannel
    status: NotificationStatus
    retry_count: int
    sent_at: datetime | None
    reference_id: uuid.UUID | None
    reference_type: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UnreadCountOut(BaseModel):
    unread_count: int
