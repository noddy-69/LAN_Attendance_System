import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DeductionPolicyOut(BaseModel):
    # "Percentage of a day's salary" late-penalty model.
    late_days_per_unit: int          # every N late days = one penalty unit
    penalty_percent_per_unit: int    # each unit costs P% of a day's salary
    grace_days: float                # first G penalty-days forgiven each month
    salary_days_per_month: int       # a day's salary = monthly_salary / D


class DeductionPolicyIn(BaseModel):
    late_days_per_unit: int = Field(ge=1, le=31)
    penalty_percent_per_unit: int = Field(ge=1, le=100)
    grace_days: float = Field(ge=0, le=31)
    salary_days_per_month: int = Field(ge=1, le=31)


class SalaryDeductionOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    month: int
    year: int
    late_count: int
    penalty_units: int                  # late_count // late_days_per_unit
    net_penalty_days: float             # penalty days deducted after grace
    monthly_salary_paise: int           # snapshot used for this calc (INTEGER paise)
    daily_salary_paise: int             # INTEGER paise
    total_deduction_paise: int          # INTEGER paise
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeductionCalculateIn(BaseModel):
    """HR triggers deduction calculation for a specific employee-month."""
    employee_id: uuid.UUID
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2020, le=2100)
