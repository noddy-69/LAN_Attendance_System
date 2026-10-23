"""
System router
=============
Endpoints:
  GET    /system/policies              — list all system policies
  GET    /system/policies/{key}        — fetch one policy by key
  PUT    /system/policies/{key}        — upsert policy value (admin)
  DELETE /system/policies/{key}        — soft-delete policy (admin)

  GET    /system/audit-logs            — paginated audit log viewer (admin)

  GET    /system/holidays              — list holiday calendar
  POST   /system/holidays              — create holiday entry
  PATCH  /system/holidays/{id}         — update holiday
  DELETE /system/holidays/{id}         — soft-delete holiday
"""
import json
import uuid
from datetime import date, datetime, timezone

# Type alias prevents the `date` field name from shadowing the `date` type import
# inside Pydantic model class bodies (Python evaluates the default before the annotation).
_Date = date

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import license as license_mod
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.rbac import require_permission
from app.core.security import get_current_user
from app.models.employee import Employee
from app.models.system import AuditAction, AuditLog, HolidayCalendar, HolidayType, SystemPolicy
from app.services.audit_service import record_audit
from app.schemas.common import ApiResponse
from app.utils.pagination import paginate

router = APIRouter(prefix="/system", tags=["system"])

_NOW = lambda: datetime.now(timezone.utc)


@router.get("/license")
async def license_status(_: Employee = Depends(get_current_user)):
    """Current software license status (company, expiry, employee cap)."""
    return ApiResponse.ok(license_mod.get_status())


# ── Pydantic schemas (inline — avoids a separate schemas/system.py) ───────────

from pydantic import BaseModel, Field


class PolicyIn(BaseModel):
    value: str = Field(description="JSON-serialized value, e.g. '3' or '\"enabled\"'")
    description: str | None = None


class PolicyOut(BaseModel):
    id: uuid.UUID
    key: str
    value: str
    description: str | None
    updated_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuditLogOut(BaseModel):
    id: uuid.UUID
    table_name: str
    record_id: uuid.UUID
    action: AuditAction
    before_value: dict | None
    after_value: dict | None
    performed_by_id: uuid.UUID | None
    performed_by_name: str | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class HolidayIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    date: date
    branch_id: uuid.UUID | None = None
    holiday_type: HolidayType = HolidayType.NATIONAL


class HolidayUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    date: _Date | None = None  # _Date alias avoids shadowing the 'date' import
    holiday_type: HolidayType | None = None


class HolidayOut(BaseModel):
    id: uuid.UUID
    name: str
    date: date
    branch_id: uuid.UUID | None
    holiday_type: HolidayType
    year: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _policy_out(p: SystemPolicy) -> PolicyOut:
    return PolicyOut(
        id=p.id,
        key=p.key,
        value=p.value,
        description=p.description,
        updated_by_id=p.updated_by_id,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _audit_out(log: AuditLog) -> AuditLogOut:
    name: str | None = None
    if log.performed_by:
        name = f"{log.performed_by.first_name} {log.performed_by.last_name}"
    return AuditLogOut(
        id=log.id,
        table_name=log.table_name,
        record_id=log.record_id,
        action=log.action,
        before_value=log.before_value,
        after_value=log.after_value,
        performed_by_id=log.performed_by_id,
        performed_by_name=name,
        ip_address=log.ip_address,
        user_agent=log.user_agent,
        created_at=log.created_at,
    )


def _holiday_out(h: HolidayCalendar) -> HolidayOut:
    return HolidayOut(
        id=h.id,
        name=h.name,
        date=h.date,
        branch_id=h.branch_id,
        holiday_type=h.holiday_type,
        year=h.year,
        created_at=h.created_at,
        updated_at=h.updated_at,
    )


# ── Data management (backup / restore / reset) — admin only (system:write) ────

class ResetIn(BaseModel):
    confirm: bool = Field(default=False, description="Must be true to proceed")


# Backups: an instant on-demand download (below) plus the automatic month-end backup
# (Celery beat -> monthly_backup, named backup_<Month>_<Year>.dump in the /backups folder).
# There is no server-side backup *list/management*; restore is only via an uploaded .dump.


@router.get("/data/backup/download")
async def download_backup(_: Employee = Depends(require_permission("system:write"))):
    """
    Take a backup right now and stream it to the browser as a `.dump` download. The file
    is written to a temp location and deleted after streaming — nothing is kept on the
    server (that's what the automatic month-end backup is for).
    """
    import asyncio
    import os as _os
    import tempfile
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask
    from app.services import data_service

    fd, tmp = tempfile.mkstemp(suffix=".dump")
    _os.close(fd)
    try:
        await asyncio.to_thread(data_service.dump_to_path, tmp)
    except Exception:
        if _os.path.exists(tmp):
            _os.remove(tmp)
        raise
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    return FileResponse(
        tmp,
        media_type="application/octet-stream",
        filename=f"attendance-backup-{ts}.dump",
        background=BackgroundTask(_os.remove, tmp),
    )


@router.post("/data/restore/upload", response_model=ApiResponse[dict])
async def restore_uploaded_backup(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("system:write")),
):
    """
    Restore from a backup file uploaded from the admin's computer (e.g. a `.dump` they
    downloaded earlier and kept off-machine). The file is validated as a real
    custom-format pg_dump, stored in the backups folder, then restored — a full
    pg_restore that replaces ALL current data. Commit this request's own session first
    so its auth query releases its table lock before pg_restore drops tables.
    """
    import asyncio
    from app.core.database import engine
    from app.services import data_service

    data = await file.read()
    filename = await asyncio.to_thread(data_service.save_uploaded_backup, data)
    await db.commit()   # release this request's locks before pg_restore drops tables
    result = await data_service.restore_from(filename, engine)
    return ApiResponse.ok(result)


@router.post("/data/reset", response_model=ApiResponse[dict])
async def reset_data(
    body: ResetIn,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("system:write")),
):
    """
    Delete transactional event data only — attendance, leave, reimbursements,
    corrections, payroll deductions and their notifications. Employees (with their
    profile pictures), enrolled face embeddings, reporting hierarchy, audit logs and
    all setup/config are preserved. Requires confirm=true.
    """
    if not body.confirm:
        from app.core.exceptions import UnprocessableError
        raise UnprocessableError("Set confirm=true to delete data.")
    from app.services import data_service
    return ApiResponse.ok(await data_service.reset_all_data(db))


# ── Policy endpoints ──────────────────────────────────────────────────────────

@router.get("/policies", response_model=ApiResponse[list[PolicyOut]])
async def list_policies(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("system:read")),
):
    """List all active system configuration policies."""
    result = await db.execute(
        select(SystemPolicy)
        .where(SystemPolicy.deleted_at.is_(None))
        .order_by(SystemPolicy.key)
    )
    policies = list(result.scalars().all())
    return ApiResponse.ok([_policy_out(p) for p in policies])


@router.get("/policies/{key}", response_model=ApiResponse[PolicyOut])
async def get_policy(
    key: str,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("system:read")),
):
    """Fetch a single system policy by its dot-notation key."""
    result = await db.execute(
        select(SystemPolicy).where(
            SystemPolicy.key == key,
            SystemPolicy.deleted_at.is_(None),
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise NotFoundError(f"Policy '{key}' not found")
    return ApiResponse.ok(_policy_out(policy))


@router.put("/policies/{key}", response_model=ApiResponse[PolicyOut])
async def upsert_policy(
    key: str,
    body: PolicyIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("system:write")),
):
    """
    Upsert a system policy by key.
    value must be a valid JSON string (e.g. '3', '"enabled"', 'true').
    """
    # Validate that value is valid JSON
    try:
        json.loads(body.value)
    except json.JSONDecodeError:
        from app.core.exceptions import UnprocessableError
        raise UnprocessableError(
            "value must be valid JSON (e.g. '3', '\"text\"', 'true', '[1,2,3]')"
        )

    stmt = (
        pg_insert(SystemPolicy)
        .values(
            id=uuid.uuid4(),
            key=key,
            value=body.value,
            description=body.description,
            updated_by_id=current_user.id,
        )
        .on_conflict_do_update(
            index_elements=["key"],
            set_={
                "value": body.value,
                "description": body.description,
                "updated_by_id": current_user.id,
                "updated_at": _NOW(),
                "deleted_at": None,   # restore if previously soft-deleted
            },
        )
    )
    await db.execute(stmt)
    await db.flush()

    result = await db.execute(
        select(SystemPolicy)
        .where(SystemPolicy.key == key)
        .execution_options(populate_existing=True)
    )
    return ApiResponse.ok(_policy_out(result.scalar_one()))


@router.delete("/policies/{key}", response_model=ApiResponse[dict])
async def delete_policy(
    key: str,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("system:write")),
):
    """Soft-delete a system policy. It will fall back to code defaults."""
    result = await db.execute(
        select(SystemPolicy).where(
            SystemPolicy.key == key,
            SystemPolicy.deleted_at.is_(None),
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise NotFoundError(f"Policy '{key}' not found")
    policy.deleted_at = _NOW()
    await db.flush()
    return ApiResponse.ok({"deleted": key})


# ── Audit log viewer ──────────────────────────────────────────────────────────

@router.get("/audit-logs", response_model=ApiResponse[list[AuditLogOut]])
async def list_audit_logs(
    table_name: str | None = Query(default=None),
    record_id: uuid.UUID | None = Query(default=None),
    action: AuditAction | None = Query(default=None),
    performed_by_id: uuid.UUID | None = Query(default=None),
    from_dt: datetime | None = Query(default=None),
    to_dt: datetime | None = Query(default=None),
    per_page: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("system:read")),
):
    """
    Paginated audit log viewer.
    AuditLog records are immutable — never soft-deleted.
    """
    stmt = (
        select(AuditLog)
        .options(selectinload(AuditLog.performed_by))
    )
    if table_name:
        stmt = stmt.where(AuditLog.table_name == table_name)
    if record_id:
        stmt = stmt.where(AuditLog.record_id == record_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if performed_by_id:
        stmt = stmt.where(AuditLog.performed_by_id == performed_by_id)
    if from_dt:
        stmt = stmt.where(AuditLog.created_at >= from_dt)
    if to_dt:
        stmt = stmt.where(AuditLog.created_at <= to_dt)

    logs, pagination = await paginate(db, stmt, AuditLog, per_page, cursor)
    return ApiResponse.ok([_audit_out(log) for log in logs], pagination)


# ── Holiday calendar ──────────────────────────────────────────────────────────

@router.get("/holidays", response_model=ApiResponse[list[HolidayOut]])
async def list_holidays(
    year: int | None = Query(default=None, ge=2020, le=2100),
    branch_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("holiday:read")),
):
    """List holidays; optionally filter by year and/or branch."""
    stmt = select(HolidayCalendar).where(HolidayCalendar.deleted_at.is_(None))
    if year:
        stmt = stmt.where(HolidayCalendar.year == year)
    if branch_id:
        # Include national holidays (branch_id IS NULL) and branch-specific ones
        from sqlalchemy import or_
        stmt = stmt.where(
            or_(
                HolidayCalendar.branch_id == branch_id,
                HolidayCalendar.branch_id.is_(None),
            )
        )
    stmt = stmt.order_by(HolidayCalendar.date)
    result = await db.execute(stmt)
    holidays = list(result.scalars().all())
    return ApiResponse.ok([_holiday_out(h) for h in holidays])


@router.post("/holidays", response_model=ApiResponse[HolidayOut], status_code=201)
async def create_holiday(
    body: HolidayIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("holiday:write")),
):
    """Add a holiday to the calendar. branch_id=null means national (all branches)."""
    from app.core.exceptions import ConflictError
    # Check for duplicate (same date + branch_id combo)
    existing = await db.execute(
        select(HolidayCalendar.id).where(
            HolidayCalendar.date == body.date,
            HolidayCalendar.branch_id == body.branch_id,
            HolidayCalendar.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(
            f"A holiday already exists on {body.date} for "
            f"{'this branch' if body.branch_id else 'all branches'}"
        )

    holiday = HolidayCalendar(
        name=body.name,
        date=body.date,
        branch_id=body.branch_id,
        holiday_type=body.holiday_type,
        year=body.date.year,
    )
    db.add(holiday)
    await db.flush()
    await db.refresh(holiday)
    await record_audit(
        db, table_name="holiday_calendar", record_id=holiday.id,
        action=AuditAction.CREATE, performed_by_id=current_user.id,
        after={"name": holiday.name, "date": str(holiday.date),
               "branch_id": str(holiday.branch_id) if holiday.branch_id else None,
               "holiday_type": holiday.holiday_type.value},
    )
    return ApiResponse.ok(_holiday_out(holiday))


@router.patch("/holidays/{holiday_id}", response_model=ApiResponse[HolidayOut])
async def update_holiday(
    holiday_id: uuid.UUID,
    body: HolidayUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("holiday:write")),
):
    """Update holiday name, date, or type."""
    result = await db.execute(
        select(HolidayCalendar).where(
            HolidayCalendar.id == holiday_id,
            HolidayCalendar.deleted_at.is_(None),
        )
    )
    holiday = result.scalar_one_or_none()
    if not holiday:
        raise NotFoundError(f"Holiday {holiday_id} not found")

    before = {"name": holiday.name, "date": str(holiday.date),
              "holiday_type": holiday.holiday_type.value}
    if body.name is not None:
        holiday.name = body.name
    if body.date is not None:
        holiday.date = body.date
        holiday.year = body.date.year
    if body.holiday_type is not None:
        holiday.holiday_type = body.holiday_type

    await db.flush()
    await db.refresh(holiday)
    await record_audit(
        db, table_name="holiday_calendar", record_id=holiday.id,
        action=AuditAction.UPDATE, performed_by_id=current_user.id,
        before=before,
        after={"name": holiday.name, "date": str(holiday.date),
               "holiday_type": holiday.holiday_type.value},
    )
    return ApiResponse.ok(_holiday_out(holiday))


@router.delete("/holidays/{holiday_id}", response_model=ApiResponse[dict])
async def delete_holiday(
    holiday_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("holiday:write")),
):
    """Soft-delete a holiday from the calendar."""
    result = await db.execute(
        select(HolidayCalendar).where(
            HolidayCalendar.id == holiday_id,
            HolidayCalendar.deleted_at.is_(None),
        )
    )
    holiday = result.scalar_one_or_none()
    if not holiday:
        raise NotFoundError(f"Holiday {holiday_id} not found")
    before = {"name": holiday.name, "date": str(holiday.date)}
    holiday.deleted_at = _NOW()
    await db.flush()
    await record_audit(
        db, table_name="holiday_calendar", record_id=holiday.id,
        action=AuditAction.DELETE, performed_by_id=current_user.id,
        before=before, after={"deleted": True},
    )
    return ApiResponse.ok({"deleted": str(holiday_id)})


# ── Weekend config (Saturday-off toggle) — managed from the Holidays section ──
# Gated on holiday permissions so BOTH admin and HR can set it (they lack system:write).

_SAT_KEY = "attendance.saturday_off"


class WeekendConfigIn(BaseModel):
    saturday_off: bool


@router.get("/weekend-config", response_model=ApiResponse[dict])
async def get_weekend_config(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("holiday:read")),
):
    """Whether Saturday is a weekly off. Sunday is always off."""
    res = await db.execute(
        select(SystemPolicy.value).where(
            SystemPolicy.key == _SAT_KEY, SystemPolicy.deleted_at.is_(None)
        )
    )
    raw = res.scalar_one_or_none()
    saturday_off = True
    if raw is not None:
        try:
            saturday_off = bool(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            saturday_off = raw.strip().lower() in ("1", "true", "yes")
    return ApiResponse.ok({"saturday_off": saturday_off})


@router.put("/weekend-config", response_model=ApiResponse[dict])
async def set_weekend_config(
    body: WeekendConfigIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("holiday:write")),
):
    """Set whether Saturday is a weekly off. Sunday is always off."""
    value = json.dumps(bool(body.saturday_off))
    stmt = (
        pg_insert(SystemPolicy)
        .values(
            id=uuid.uuid4(), key=_SAT_KEY, value=value,
            description="Whether Saturday counts as a weekly off",
            updated_by_id=current_user.id,
        )
        .on_conflict_do_update(
            index_elements=["key"],
            set_={
                "value": value,
                "updated_by_id": current_user.id,
                "updated_at": _NOW(),
                "deleted_at": None,
            },
        )
    )
    await db.execute(stmt)
    await db.flush()
    return ApiResponse.ok({"saturday_off": bool(body.saturday_off)})
