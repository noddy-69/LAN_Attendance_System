import uuid
from datetime import time

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, String, Text, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Branch(Base):
    __tablename__ = "branches"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)

    # Used by the attendance engine for late-arrival calculation
    office_start_time: Mapped[time] = mapped_column(Time, nullable=False)
    office_end_time: Mapped[time] = mapped_column(Time, nullable=False)
    # NULL = inherit the org-wide default (system_policies['attendance.grace_period_minutes']).
    # A number = this branch's explicit override (0 = truly no grace).
    grace_period_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )

    departments: Mapped[list["Department"]] = relationship(
        "Department", back_populates="branch"
    )
    employees: Mapped[list["Employee"]] = relationship(
        "Employee", back_populates="branch", foreign_keys="[Employee.branch_id]"
    )
    devices: Mapped[list["Device"]] = relationship(
        "Device", back_populates="branch"
    )
    holidays: Mapped[list["HolidayCalendar"]] = relationship(
        "HolidayCalendar", back_populates="branch"
    )
    shifts: Mapped[list["ShiftDefinition"]] = relationship(
        "ShiftDefinition", back_populates="branch"
    )


class Department(Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Circular reference with Employee — deferred as ALTER TABLE
    head_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "employees.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_departments_head_employee_id",
        ),
        nullable=True,
    )

    branch: Mapped[Branch] = relationship("Branch", back_populates="departments")
    head_employee: Mapped["Employee | None"] = relationship(
        "Employee", foreign_keys=[head_employee_id]
    )
    employees: Mapped[list["Employee"]] = relationship(
        "Employee",
        back_populates="department",
        foreign_keys="[Employee.department_id]",
    )
