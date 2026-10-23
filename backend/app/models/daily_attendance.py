import enum
import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.attendance_event import AttendanceSource
from app.models.base import Base


class AttendanceStatus(str, enum.Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    HALF_DAY = "HALF_DAY"
    LATE = "LATE"
    ON_LEAVE = "ON_LEAVE"
    HOLIDAY = "HOLIDAY"
    WEEKEND = "WEEKEND"
    PENDING_CORRECTION = "PENDING_CORRECTION"


class DailyAttendance(Base):
    __tablename__ = "daily_attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_daily_attendance_employee_date"),
        Index("ix_daily_attendance_employee_date", "employee_id", "date"),
        Index("ix_daily_attendance_status", "status"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)

    # Derived from first ENTRY / last EXIT attendance_event of the day
    check_in: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    check_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # All durations stored as whole minutes (integers)
    work_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overtime_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    late_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    is_late: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false()
    )

    status: Mapped[AttendanceStatus] = mapped_column(
        sa.Enum(AttendanceStatus, name="attendance_status"), nullable=False
    )
    source: Mapped[AttendanceSource] = mapped_column(
        # Re-uses the PostgreSQL ENUM created in attendance_events; do not recreate it
        sa.Enum(AttendanceSource, name="attendance_source", create_type=False),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    employee: Mapped["Employee"] = relationship(
        "Employee", back_populates="daily_attendance"
    )
