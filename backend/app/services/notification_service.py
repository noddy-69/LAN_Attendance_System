"""
Notification Service
====================
List notifications and mark them read/unread for the in-app feed.

Delivery status semantics used by mark_read:
  PENDING     → notification not yet shown / acknowledged by the employee
  SENT        → delivered (WhatsApp/email) or acknowledged (in-app)

"Mark as read" transitions PENDING → SENT for in-app and any channel that
hasn't been delivered yet.  Notifications already SENT/FAILED are left as-is.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.notification import Notification, NotificationStatus
from app.schemas.common import PaginationMeta
from app.utils.pagination import paginate

_NOW = lambda: datetime.now(timezone.utc)


async def list_notifications(
    db: AsyncSession,
    employee_id: uuid.UUID,
    *,
    unread_only: bool = False,
    per_page: int = 20,
    cursor: str | None = None,
) -> tuple[list[Notification], PaginationMeta]:
    stmt = select(Notification).where(
        Notification.employee_id == employee_id,
        Notification.deleted_at.is_(None),
    )
    if unread_only:
        stmt = stmt.where(Notification.status == NotificationStatus.PENDING)
    return await paginate(db, stmt, Notification, per_page, cursor)


async def get_notification(
    db: AsyncSession,
    notification_id: uuid.UUID,
) -> Notification:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.deleted_at.is_(None),
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise NotFoundError(f"Notification {notification_id} not found")
    return notif


async def mark_read(
    db: AsyncSession,
    notification_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> Notification:
    notif = await get_notification(db, notification_id)
    if notif.employee_id != employee_id:
        raise ForbiddenError("Cannot mark another employee's notification as read")
    if notif.status == NotificationStatus.PENDING:
        notif.status = NotificationStatus.SENT
        notif.sent_at = _NOW()
        await db.flush()
        await db.refresh(notif)
    return notif


async def mark_all_read(
    db: AsyncSession,
    employee_id: uuid.UUID,
) -> int:
    """Mark every PENDING notification as SENT for the employee. Returns count updated."""
    result = await db.execute(
        select(Notification).where(
            Notification.employee_id == employee_id,
            Notification.status == NotificationStatus.PENDING,
            Notification.deleted_at.is_(None),
        )
    )
    notifs = list(result.scalars().all())
    now = _NOW()
    for n in notifs:
        n.status = NotificationStatus.SENT
        n.sent_at = now
    if notifs:
        await db.flush()
    return len(notifs)


async def unread_count(db: AsyncSession, employee_id: uuid.UUID) -> int:
    from sqlalchemy import func, select as sa_select
    result = await db.execute(
        sa_select(func.count()).where(
            Notification.employee_id == employee_id,
            Notification.status == NotificationStatus.PENDING,
            Notification.deleted_at.is_(None),
        )
    )
    return result.scalar_one()
