import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, Field

from app.models.system import HolidayType


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    address: str | None = None
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    office_start_time: time
    office_end_time: time
    # None = inherit the org-wide default set in Admin → Settings.
    grace_period_minutes: int | None = Field(default=None, ge=0, le=120)


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    address: str | None = None
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = Field(default=None, min_length=1, max_length=100)
    office_start_time: time | None = None
    office_end_time: time | None = None
    grace_period_minutes: int | None = Field(default=None, ge=0, le=120)


class BranchOut(BaseModel):
    id: uuid.UUID
    name: str
    address: str | None
    city: str
    state: str
    office_start_time: time
    office_end_time: time
    grace_period_minutes: int | None
    employee_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HolidayCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    date: date
    holiday_type: HolidayType
    year: int = Field(ge=2020, le=2100)


class HolidayOut(BaseModel):
    id: uuid.UUID
    name: str
    date: date
    branch_id: uuid.UUID | None
    holiday_type: HolidayType
    year: int
    created_at: datetime

    model_config = {"from_attributes": True}
