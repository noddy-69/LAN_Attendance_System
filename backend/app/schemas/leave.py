import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.models.leave import LeaveStatus


# ── Leave types ───────────────────────────────────────────────────────────────

class LeaveTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=10)
    days_per_year: int = Field(ge=0)
    is_paid: bool = True
    requires_approval: bool = True
    carry_forward: bool = False
    max_carry_forward_days: int = Field(default=0, ge=0)
    description: str | None = None


class LeaveTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    days_per_year: int | None = Field(default=None, ge=0)
    is_paid: bool | None = None
    requires_approval: bool | None = None
    carry_forward: bool | None = None
    max_carry_forward_days: int | None = Field(default=None, ge=0)
    description: str | None = None


class LeaveTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    days_per_year: int
    is_paid: bool
    requires_approval: bool
    carry_forward: bool
    max_carry_forward_days: int
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Leave requests ────────────────────────────────────────────────────────────

class LeaveApplyIn(BaseModel):
    leave_type_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str = Field(min_length=1, max_length=2000)
    is_half_day: bool = False

    @model_validator(mode="after")
    def _dates_valid(self) -> "LeaveApplyIn":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.is_half_day and self.start_date != self.end_date:
            raise ValueError("is_half_day requires start_date == end_date (single day only)")
        return self


class LeaveActionIn(BaseModel):
    """Shared body for all approve/reject actions."""
    remarks: str | None = Field(default=None, max_length=1000)


class LeaveRequestOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str        # "{first} {last}"
    leave_type_id: uuid.UUID
    leave_type_name: str
    leave_type_code: str
    start_date: date
    end_date: date
    days_requested: float
    is_half_day: bool
    reason: str
    status: LeaveStatus

    manager_id: uuid.UUID | None
    manager_name: str | None
    manager_action_at: datetime | None
    manager_remarks: str | None

    hr_id: uuid.UUID | None
    hr_name: str | None
    hr_action_at: datetime | None
    hr_remarks: str | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Leave balance ─────────────────────────────────────────────────────────────

class LeaveBalanceOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    leave_type_id: uuid.UUID
    leave_type_name: str
    leave_type_code: str
    year: int
    allocated_days: float
    carried_forward_days: float
    used_days: float
    available_days: float   # computed: allocated + carried_forward - used

    model_config = {"from_attributes": True}


class LeaveBalanceAdjustIn(BaseModel):
    """HR manually adjusts a balance (e.g. to grant extra days)."""
    employee_id: uuid.UUID
    leave_type_id: uuid.UUID
    year: int
    allocated_days: float = Field(ge=0)
    carried_forward_days: float = Field(default=0.0, ge=0)
