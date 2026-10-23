import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Employee(Base):
    __tablename__ = "employees"

    employee_code: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Foreign keys ─────────────────────────────────────────────────
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shift_definitions.id", ondelete="SET NULL"), nullable=True
    )
    # Self-referential: direct manager
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Operational ──────────────────────────────────────────────────
    # UID configured on ZKTeco K40 device; used to map biometric events
    biometric_uid: Mapped[str | None] = mapped_column(
        String(50), nullable=True, unique=True
    )
    date_of_joining: Mapped[date] = mapped_column(Date, nullable=False)
    date_of_leaving: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Gross monthly salary in INTEGER paise (₹1 = 100 paise). Drives the
    # percentage-of-a-day late-penalty deduction. 0 = not set (no deduction).
    monthly_salary_paise: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )

    # ── Auth ─────────────────────────────────────────────────────────
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Relationships ────────────────────────────────────────────────
    role: Mapped["Role"] = relationship("Role", back_populates="employees")
    branch: Mapped["Branch"] = relationship(
        "Branch", back_populates="employees", foreign_keys=[branch_id]
    )
    department: Mapped["Department | None"] = relationship(
        "Department",
        back_populates="employees",
        foreign_keys=[department_id],
    )
    shift: Mapped["ShiftDefinition | None"] = relationship(
        "ShiftDefinition", back_populates="employees"
    )
    # Direct manager (many-to-one self-ref)
    manager: Mapped["Employee | None"] = relationship(
        "Employee",
        foreign_keys=[manager_id],
        remote_side="Employee.id",
        back_populates="direct_reports",
    )
    direct_reports: Mapped[list["Employee"]] = relationship(
        "Employee",
        foreign_keys=[manager_id],
        back_populates="manager",
    )

    leave_requests: Mapped[list["LeaveRequest"]] = relationship(
        "LeaveRequest",
        back_populates="employee",
        foreign_keys="[LeaveRequest.employee_id]",
    )
    leave_balances: Mapped[list["LeaveBalance"]] = relationship(
        "LeaveBalance", back_populates="employee"
    )
    reimbursements: Mapped[list["Reimbursement"]] = relationship(
        "Reimbursement",
        back_populates="employee",
        foreign_keys="[Reimbursement.employee_id]",
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="employee"
    )
    salary_deductions: Mapped[list["SalaryDeduction"]] = relationship(
        "SalaryDeduction", back_populates="employee"
    )
    face_embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        "FaceEmbedding", back_populates="employee"
    )
    daily_attendance: Mapped[list["DailyAttendance"]] = relationship(
        "DailyAttendance", back_populates="employee"
    )
    attendance_events: Mapped[list["AttendanceEvent"]] = relationship(
        "AttendanceEvent",
        back_populates="employee",
        foreign_keys="[AttendanceEvent.employee_id]",
    )
