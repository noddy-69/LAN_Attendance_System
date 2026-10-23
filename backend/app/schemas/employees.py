import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class EmployeeCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=20)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, description="Plain-text; hashed by the service layer")
    role_id: uuid.UUID
    branch_id: uuid.UUID
    department_id: uuid.UUID | None = None
    shift_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    biometric_uid: str | None = Field(default=None, max_length=50)
    date_of_joining: date
    # Gross monthly salary in INTEGER paise (₹1 = 100 paise). 0 = not set.
    monthly_salary_paise: int = Field(default=0, ge=0)


class EmployeeUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    password: str | None = Field(default=None, min_length=8, description="Admin password reset; hashed by the service layer, never logged")
    role_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    shift_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    biometric_uid: str | None = Field(default=None, max_length=50)
    date_of_leaving: date | None = None
    is_active: bool | None = None
    monthly_salary_paise: int | None = Field(default=None, ge=0)


class EmployeeOut(BaseModel):
    id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str
    email: str
    phone: str | None
    role_id: uuid.UUID
    role_name: str
    branch_id: uuid.UUID
    branch_name: str
    department_id: uuid.UUID | None
    department_name: str | None
    shift_id: uuid.UUID | None
    manager_id: uuid.UUID | None
    manager_name: str | None  # "{first} {last}" of direct manager
    biometric_uid: str | None
    date_of_joining: date
    date_of_leaving: date | None
    is_active: bool
    monthly_salary_paise: int
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DirectReportOut(BaseModel):
    id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str
    email: str
    role_name: str
    is_active: bool

    model_config = {"from_attributes": True}


class HierarchyNodeOut(BaseModel):
    id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str
    role_name: str
    depth: int  # 0 = self, 1 = direct manager, 2 = manager's manager…
