import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    branch_id: uuid.UUID
    head_employee_id: uuid.UUID | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    branch_id: uuid.UUID | None = None
    head_employee_id: uuid.UUID | None = None


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    branch_id: uuid.UUID
    branch_name: str
    head_employee_id: uuid.UUID | None
    head_employee_name: str | None  # "{first} {last}"
    employee_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
