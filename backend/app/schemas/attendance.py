import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.attendance_event import AttendanceSource, EventType
from app.models.attendance_proof import ProofType
from app.models.daily_attendance import AttendanceStatus


# ── Inbound event payloads ────────────────────────────────────────────────────

class CameraEventIn(BaseModel):
    """Posted by the face-recognition microservice."""
    employee_id: uuid.UUID
    # The face service may run without a registered device row (e.g. webcam test
    # mode), in which case it sends null and the event is stored deviceless.
    device_id: uuid.UUID | None = None
    branch_id: uuid.UUID
    event_type: EventType
    timestamp: datetime            # UTC from the camera frame capture
    confidence_score: float = Field(ge=0.0, le=1.0)
    proof_storage_path: str | None = None   # MinIO object key of the frame


class BiometricEventIn(BaseModel):
    """ZKTeco K40 ADMS push payload (sent directly by the device)."""
    sn: str      # device serial number — maps to Device.device_uid
    ret: str = "0"
    cmd: str = "att"
    uid: str     # employee biometric UID — maps to Employee.biometric_uid
    time: str    # "YYYY-MM-DD HH:MM:SS" in device local time (IST)
    state: str   # "0" = ENTRY (BIOMETRIC_CHECKIN_STATE), else EXIT
    ty: str = "1"


class ManualEventIn(BaseModel):
    """HR/Manager direct manual entry."""
    employee_id: uuid.UUID
    event_type: EventType
    timestamp: datetime    # UTC
    notes: str | None = None


# ── Response schemas ──────────────────────────────────────────────────────────

class AttendanceEventOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    branch_id: uuid.UUID
    device_id: uuid.UUID | None
    event_type: EventType
    source: AttendanceSource
    raw_timestamp: datetime
    corrected_timestamp: datetime | None
    confidence_score: float | None
    biometric_uid: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DailyAttendanceOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    date: date
    check_in: datetime | None
    check_out: datetime | None
    work_minutes: int | None
    overtime_minutes: int
    late_minutes: int
    is_late: bool
    status: AttendanceStatus
    source: AttendanceSource
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyOverrideIn(BaseModel):
    """HR manual override — supply any subset of fields."""
    check_in: datetime | None = None
    check_out: datetime | None = None
    status: AttendanceStatus | None = None
    notes: str | None = None


class ProofOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    proof_type: ProofType
    url: str          # presigned MinIO URL (1-hour expiry)
    captured_at: datetime


class CorrectionRequestIn(BaseModel):
    date: date
    requested_check_in: datetime | None = None
    requested_check_out: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)


class CorrectionActionIn(BaseModel):
    remarks: str | None = None


class CorrectionOut(BaseModel):
    """Correction info derived from DailyAttendance.notes + main fields."""
    daily_id: uuid.UUID
    employee_id: uuid.UUID
    date: date
    # "pending" → "pending_hr" → "approved" | "rejected"
    correction_status: str
    requested_check_in: datetime | None
    requested_check_out: datetime | None
    reason: str
    manager_remarks: str | None
    hr_remarks: str | None
    remarks: str | None             # final approver's remarks (HR or single-step)
    current_attendance_status: AttendanceStatus
    proof_url: str | None = None    # presigned URL for the optional supporting proof
