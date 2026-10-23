import enum
import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class LeaveStatus(str, enum.Enum):
    PENDING_MANAGER = "pending_manager"
    PENDING_HR = "pending_hr"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LeaveType(Base):
    __tablename__ = "leave_types"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Short code used in reports — e.g. "AL", "SL", "CL"
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    days_per_year: Mapped[int] = mapped_column(Integer, nullable=False)
    is_paid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )
    carry_forward: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false()
    )
    max_carry_forward_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    leave_requests: Mapped[list["LeaveRequest"]] = relationship(
        "LeaveRequest", back_populates="leave_type"
    )
    leave_balances: Mapped[list["LeaveBalance"]] = relationship(
        "LeaveBalance", back_populates="leave_type"
    )


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leave_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_requested: Mapped[float] = mapped_column(sa.Numeric(5, 1), nullable=False)
    is_half_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false()
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[LeaveStatus] = mapped_column(
        sa.Enum(LeaveStatus, name="leave_status"),
        nullable=False,
        default=LeaveStatus.PENDING_MANAGER,
        index=True,
    )

    # Manager approval step
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    manager_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    manager_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # HR final approval step
    hr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    hr_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hr_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    employee: Mapped["Employee"] = relationship(
        "Employee",
        back_populates="leave_requests",
        foreign_keys=[employee_id],
    )
    leave_type: Mapped[LeaveType] = relationship(
        "LeaveType", back_populates="leave_requests"
    )
    approving_manager: Mapped["Employee | None"] = relationship(
        "Employee", foreign_keys=[manager_id]
    )
    approving_hr: Mapped["Employee | None"] = relationship(
        "Employee", foreign_keys=[hr_id]
    )


class LeaveBalance(Base):
    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "leave_type_id", "year",
            name="uq_leave_balance_employee_type_year",
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leave_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_days: Mapped[float] = mapped_column(sa.Numeric(5, 1), nullable=False)
    used_days: Mapped[float] = mapped_column(
        sa.Numeric(5, 1), nullable=False, default=0, server_default="0"
    )
    carried_forward_days: Mapped[float] = mapped_column(
        sa.Numeric(5, 1), nullable=False, default=0, server_default="0"
    )

    employee: Mapped["Employee"] = relationship(
        "Employee", back_populates="leave_balances"
    )
    leave_type: Mapped[LeaveType] = relationship(
        "LeaveType", back_populates="leave_balances"
    )
