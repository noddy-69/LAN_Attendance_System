import enum
import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class HolidayType(str, enum.Enum):
    NATIONAL = "national"
    REGIONAL = "regional"
    OPTIONAL = "optional"


class AuditAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"


class SystemPolicy(Base):
    __tablename__ = "system_policies"

    # Dot-notation key — e.g. "payroll.allowed_late_count", "attendance.grace_period"
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # JSON-serialised value for flexibility (int, bool, string, list)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )

    updated_by: Mapped["Employee | None"] = relationship("Employee")


class HolidayCalendar(Base):
    __tablename__ = "holiday_calendar"
    __table_args__ = (
        UniqueConstraint("date", "branch_id", name="uq_holiday_date_branch"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # NULL → applies to all branches (national holiday)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    holiday_type: Mapped[HolidayType] = mapped_column(
        sa.Enum(HolidayType, name="holiday_type"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    branch: Mapped["Branch | None"] = relationship(
        "Branch", back_populates="holidays"
    )


class AuditLog(Base):
    """Immutable audit trail — never update or soft-delete these rows."""

    __tablename__ = "audit_logs"

    table_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    action: Mapped[AuditAction] = mapped_column(
        sa.Enum(AuditAction, name="audit_action"), nullable=False
    )
    # JSONB for structured diffs — supports key-level queries
    before_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    performed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    performed_by: Mapped["Employee | None"] = relationship("Employee")
