"""
Notifications router
====================
Endpoints:
  GET   /notifications             — list current user's notifications
  GET   /notifications/unread-count — quick unread badge count
  PATCH /notifications/{id}/read   — mark one notification as read
  PATCH /notifications/read-all    — mark all notifications as read

"Read" = status transitions from PENDING → SENT (in-app acknowledgement).
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_permission
from app.models.employee import Employee
from app.schemas.common import ApiResponse
from app.schemas.notifications import NotificationOut, UnreadCountOut
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _notif_out(n) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        employee_id=n.employee_id,
        event_type=n.event_type,
        title=n.title,
        body=n.body,
        channel=n.channel,
        status=n.status,
        retry_count=n.retry_count,
        sent_at=n.sent_at,
        reference_id=n.reference_id,
        reference_type=n.reference_type,
        created_at=n.created_at,
        updated_at=n.updated_at,
    )


@router.get("", response_model=ApiResponse[list[NotificationOut]])
async def list_notifications(
    unread_only: bool = Query(default=False),
    per_page: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("notification:read")),
):
    """Return the current employee's notification feed, newest first."""
    notifs, pagination = await notification_service.list_notifications(
        db,
        employee_id=current_user.id,
        unread_only=unread_only,
        per_page=per_page,
        cursor=cursor,
    )
    return ApiResponse.ok([_notif_out(n) for n in notifs], pagination)


@router.get("/unread-count", response_model=ApiResponse[UnreadCountOut])
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("notification:read")),
):
    """Return the number of unread (PENDING) notifications for badge display."""
    count = await notification_service.unread_count(db, current_user.id)
    return ApiResponse.ok(UnreadCountOut(unread_count=count))


@router.patch("/{notification_id}/read", response_model=ApiResponse[NotificationOut])
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("notification:read")),
):
    """Mark a single notification as read (PENDING → SENT)."""
    notif = await notification_service.mark_read(db, notification_id, current_user.id)
    return ApiResponse.ok(_notif_out(notif))


@router.patch("/read-all", response_model=ApiResponse[dict])
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("notification:read")),
):
    """Mark all of the current employee's PENDING notifications as read."""
    updated = await notification_service.mark_all_read(db, current_user.id)
    return ApiResponse.ok({"updated": updated})
