import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.reimbursement import ReimbursementCategory, ReimbursementStatus


class ReimbursementSubmitIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    # Stored as INTEGER paise — 1 rupee = 100 paise. Never float.
    amount_paise: int = Field(gt=0, description="Amount in paise (₹1 = 100p). Integer only.")
    category: ReimbursementCategory
    expense_date: date


class ReimbursementActionIn(BaseModel):
    remarks: str | None = Field(default=None, max_length=1000)


class DocumentOut(BaseModel):
    id: uuid.UUID
    file_name: str
    url: str | None        # presigned MinIO URL (1-hour expiry); None in list views
    file_size_bytes: int
    mime_type: str


class ReimbursementOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    title: str
    description: str | None
    # INTEGER paise — frontend divides by 100 to display ₹
    amount_paise: int
    category: ReimbursementCategory
    expense_date: date
    status: ReimbursementStatus

    manager_id: uuid.UUID | None
    manager_name: str | None
    manager_action_at: datetime | None
    manager_remarks: str | None

    hr_id: uuid.UUID | None
    hr_name: str | None
    hr_action_at: datetime | None
    hr_remarks: str | None
    paid_at: datetime | None

    document_count: int
    documents: list[DocumentOut]   # presigned URLs only in detail endpoint

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
