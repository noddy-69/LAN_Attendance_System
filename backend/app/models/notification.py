import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class NotificationEvent(str, enum.Enum):
    ATTENDANCE_MARKED = "attendance_marked"   # retained for historical rows; no longer emitted
    ABSENT_ALERT = "absent_alert"
    LATE_ARRIVAL = "late_arrival"
    LEAVE_APPLIED = "leave_applied"
    LEAVE_APPROVED = "leave_approved"
    LEAVE_REJECTED = "leave_rejected"
    REIMBURSEMENT_UPDATE = "reimbursement_update"
    PAYROLL_DEDUCTION = "payroll_deduction"
    CORRECTION_STATUS = "correction_status"


class NotificationChannel(str, enum.Enum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    IN_APP = "in_app"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    # Stored when no internet; retried by Celery beat when connectivity returns
    QUEUED_OFFLINE = "queued_offline"


class Notification(Base):
    __tablename__ = "notifications"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[NotificationEvent] = mapped_column(
        sa.Enum(NotificationEvent, name="notification_event"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    channel: Mapped[NotificationChannel] = mapped_column(
        sa.Enum(NotificationChannel, name="notification_channel"), nullable=False
    )
    status: Mapped[NotificationStatus] = mapped_column(
        sa.Enum(NotificationStatus, name="notification_status"),
        nullable=False,
        default=NotificationStatus.PENDING,
        index=True,
    )

    celery_task_id: Mapped[str | None] = mapped_column(String(155), nullable=True)
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Polymorphic reference to the triggering entity (leave_request, attendance, etc.)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    employee: Mapped["Employee"] = relationship(
        "Employee", back_populates="notifications"
    )
