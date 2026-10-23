"""
Leave Management Service
========================

Approval flow:
    Employee applies → PENDING_MANAGER
    Manager approves → PENDING_HR
    HR approves      → APPROVED  (balance deducted, daily_attendance set ON_LEAVE)
    Manager/HR rejects at any step → REJECTED
    Employee cancels  → CANCELLED  (balance restored + ON_LEAVE reverted if was APPROVED)

Balance:
    - Auto-created on first apply (allocated_days = leave_type.days_per_year)
    - Deducted with SELECT FOR UPDATE to prevent double-booking
    - Restored atomically on cancel-after-approval or HR-reject-after-manager-approve
    - Stored as NUMERIC(5,1) — supports 0.5-day half-day leave
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.models.attendance_event import AttendanceSource
from app.models.daily_attendance import AttendanceStatus, DailyAttendance
from app.models.employee import Employee
from app.models.leave import LeaveBalance, LeaveRequest, LeaveStatus, LeaveType
from app.models.system import AuditAction, AuditLog, HolidayCalendar
from app.services.audit_service import record_audit
from app.schemas.common import PaginationMeta
from app.schemas.leave import LeaveApplyIn, LeaveBalanceAdjustIn, LeaveTypeCreate, LeaveTypeUpdate
from app.utils.pagination import paginate

_NOW = lambda: datetime.now(timezone.utc)


# ── Daily-attendance ON_LEAVE helpers ─────────────────────────────────────────

async def _mark_on_leave(
    db: AsyncSession,
    employee_id: uuid.UUID,
    start_date: date,
    end_date: date,
    is_half_day: bool = False,
    branch_id: uuid.UUID | None = None,
) -> None:
    """Upsert daily_attendance rows for each working day in [start, end] to ON_LEAVE or HALF_DAY."""
    status = AttendanceStatus.HALF_DAY if is_half_day else AttendanceStatus.ON_LEAVE
    cur = start_date
    while cur <= end_date:
        if cur.weekday() < 5:  # Mon-Fri only; weekends stay WEEKEND
            result = await db.execute(
                select(DailyAttendance).where(
                    DailyAttendance.employee_id == employee_id,
                    DailyAttendance.date == cur,
                    DailyAttendance.deleted_at.is_(None),
                )
            )
            daily = result.scalar_one_or_none()
            if daily:
                daily.status = status
            else:
                daily = DailyAttendance(
                    employee_id=employee_id,
                    date=cur,
                    status=status,
                    source=AttendanceSource.MANUAL,
                )
                db.add(daily)
        cur += timedelta(days=1)
    await db.flush()


async def _revert_on_leave(
    db: AsyncSession,
    employee_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> None:
    """After cancellation of approved leave, revert ON_LEAVE/HALF_DAY rows back to ABSENT."""
    cur = start_date
    while cur <= end_date:
        result = await db.execute(
            select(DailyAttendance).where(
                DailyAttendance.employee_id == employee_id,
                DailyAttendance.date == cur,
                DailyAttendance.deleted_at.is_(None),
            )
        )
        daily = result.scalar_one_or_none()
        if daily and daily.status in (AttendanceStatus.ON_LEAVE, AttendanceStatus.HALF_DAY):
            daily.status = AttendanceStatus.ABSENT
        cur += timedelta(days=1)
    await db.flush()


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_request_or_404(db: AsyncSession, request_id: uuid.UUID) -> LeaveRequest:
    result = await db.execute(
        select(LeaveRequest)
        .where(LeaveRequest.id == request_id, LeaveRequest.deleted_at.is_(None))
        .options(
            selectinload(LeaveRequest.leave_type),
            selectinload(LeaveRequest.employee),
            selectinload(LeaveRequest.approving_manager),
            selectinload(LeaveRequest.approving_hr),
        )
    )
    req = result.scalar_one_or_none()
    if not req:
        raise NotFoundError(f"Leave request {request_id} not found")
    return req


async def _get_or_create_balance(
    db: AsyncSession,
    employee_id: uuid.UUID,
    leave_type_id: uuid.UUID,
    year: int,
) -> LeaveBalance:
    """
    Fetch the balance row WITH a row-level lock (FOR UPDATE) to prevent
    concurrent double-booking.  Auto-creates with the leave type's days_per_year
    if no balance exists yet.
    """
    # Try to load existing row with lock
    result = await db.execute(
        select(LeaveBalance)
        .where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.leave_type_id == leave_type_id,
            LeaveBalance.year == year,
        )
        .with_for_update()
    )
    balance = result.scalar_one_or_none()

    if balance is None:
        # Auto-initialise: fetch leave_type to get days_per_year
        lt_result = await db.execute(
            select(LeaveType).where(LeaveType.id == leave_type_id)
        )
        lt = lt_result.scalar_one_or_none()
        if not lt:
            raise NotFoundError(f"Leave type {leave_type_id} not found")

        balance = LeaveBalance(
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            year=year,
            allocated_days=lt.days_per_year,
            used_days=0,
            carried_forward_days=0,
        )
        db.add(balance)
        await db.flush()

    return balance


async def _available_days(balance: LeaveBalance) -> float:
    return float(balance.allocated_days) + float(balance.carried_forward_days) - float(balance.used_days)


# ── Leave-type CRUD ───────────────────────────────────────────────────────────

async def list_leave_types(db: AsyncSession) -> list[LeaveType]:
    result = await db.execute(
        select(LeaveType)
        .where(LeaveType.deleted_at.is_(None))
        .order_by(LeaveType.name)
    )
    return list(result.scalars().all())


async def get_leave_type(db: AsyncSession, lt_id: uuid.UUID) -> LeaveType:
    result = await db.execute(
        select(LeaveType).where(
            LeaveType.id == lt_id, LeaveType.deleted_at.is_(None)
        )
    )
    lt = result.scalar_one_or_none()
    if not lt:
        raise NotFoundError(f"Leave type {lt_id} not found")
    return lt


async def create_leave_type(db: AsyncSession, data: LeaveTypeCreate) -> LeaveType:
    dup = await db.execute(
        select(LeaveType.id).where(
            LeaveType.code == data.code, LeaveType.deleted_at.is_(None)
        )
    )
    if dup.scalar_one_or_none():
        raise ConflictError(f"Leave type with code '{data.code}' already exists")

    lt = LeaveType(**data.model_dump())
    db.add(lt)
    await db.flush()
    await db.refresh(lt)
    return lt


async def update_leave_type(
    db: AsyncSession, lt_id: uuid.UUID, data: LeaveTypeUpdate
) -> LeaveType:
    lt = await get_leave_type(db, lt_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(lt, field, value)
    await db.flush()
    await db.refresh(lt)
    return lt


async def delete_leave_type(db: AsyncSession, lt_id: uuid.UUID) -> None:
    lt = await get_leave_type(db, lt_id)
    # Check no active requests reference this leave type
    active = await db.execute(
        select(LeaveRequest.id).where(
            LeaveRequest.leave_type_id == lt_id,
            LeaveRequest.status.in_(
                [LeaveStatus.PENDING_MANAGER, LeaveStatus.PENDING_HR, LeaveStatus.APPROVED]
            ),
            LeaveRequest.deleted_at.is_(None),
        )
    )
    if active.scalar_one_or_none():
        raise UnprocessableError("Cannot delete: active leave requests reference this type")
    lt.deleted_at = _NOW()
    await db.flush()


# ── Leave request lifecycle ───────────────────────────────────────────────────

async def apply(
    db: AsyncSession,
    employee_id: uuid.UUID,
    data: LeaveApplyIn,
) -> LeaveRequest:
    """Employee submits a leave request."""
    # Validate leave type exists
    lt = await get_leave_type(db, data.leave_type_id)

    # Compute days to deduct (0.5 for half-day, else calendar days inclusive)
    days: float = 0.5 if data.is_half_day else float((data.end_date - data.start_date).days + 1)

    # ── Holiday check — reject if any date in range is a holiday ──────────────
    emp_result = await db.execute(
        select(Employee.branch_id).where(Employee.id == employee_id)
    )
    emp_branch_id = emp_result.scalar_one_or_none()

    holiday_result = await db.execute(
        select(HolidayCalendar).where(
            HolidayCalendar.date >= data.start_date,
            HolidayCalendar.date <= data.end_date,
            HolidayCalendar.deleted_at.is_(None),
            or_(
                HolidayCalendar.branch_id.is_(None),
                HolidayCalendar.branch_id == emp_branch_id,
            ),
        ).limit(1)
    )
    holiday = holiday_result.scalar_one_or_none()
    if holiday:
        raise UnprocessableError(
            f"Cannot apply for leave on {holiday.date}: "
            f"'{holiday.name}' is a holiday. Holidays are automatically considered non-working days."
        )

    # ── Overlap check ──────────────────────────────────────────────────────────
    overlap = await db.execute(
        select(LeaveRequest.id).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.deleted_at.is_(None),
            LeaveRequest.status.in_(
                [LeaveStatus.PENDING_MANAGER, LeaveStatus.PENDING_HR, LeaveStatus.APPROVED]
            ),
            LeaveRequest.start_date <= data.end_date,
            LeaveRequest.end_date >= data.start_date,
        )
    )
    if overlap.scalar_one_or_none():
        raise ConflictError(
            "A pending or approved leave request already exists for these dates"
        )

    # ── Balance check — hard reject if insufficient ───────────────────────────
    balance = await _get_or_create_balance(
        db, employee_id, data.leave_type_id, data.start_date.year
    )
    available = await _available_days(balance)
    if available < days:
        raise UnprocessableError(
            f"Insufficient leave balance: {available:.1f} day(s) available, "
            f"{days:.1f} requested. Apply for fewer days or contact HR to adjust your balance."
        )

    # ── Create request ─────────────────────────────────────────────────────────
    if lt.requires_approval:
        initial_status = LeaveStatus.PENDING_MANAGER
    else:
        # Auto-approved (e.g. Sick Leave) — deduct balance immediately
        initial_status = LeaveStatus.APPROVED
        balance.used_days = float(balance.used_days) + days
        await db.flush()

    req = LeaveRequest(
        employee_id=employee_id,
        leave_type_id=data.leave_type_id,
        start_date=data.start_date,
        end_date=data.end_date,
        days_requested=days,
        is_half_day=data.is_half_day,
        reason=data.reason,
        status=initial_status,
    )
    db.add(req)
    await db.flush()

    # Auto-approved: mark daily_attendance immediately
    if initial_status == LeaveStatus.APPROVED:
        await _mark_on_leave(
            db, employee_id, data.start_date, data.end_date,
            is_half_day=data.is_half_day, branch_id=emp_branch_id,
        )

    final_req = await _get_request_or_404(db, req.id)

    await record_audit(
        db, table_name="leave_requests", record_id=req.id,
        action=AuditAction.CREATE, performed_by_id=employee_id,
        after={"leave_type": lt.name, "days": float(days),
               "start_date": str(data.start_date), "end_date": str(data.end_date),
               "status": final_req.status.value},
    )

    from app.tasks.notifications import send_notification
    send_notification.delay(
        str(employee_id),
        "LEAVE_APPLIED",
        leave_type=lt.name,
        days=days,
        start_date=str(data.start_date),
        reference_id=str(req.id),
        reference_type="leave_requests",
    )

    return final_req


async def manager_approve(
    db: AsyncSession,
    request_id: uuid.UUID,
    manager_id: uuid.UUID,
    remarks: str | None,
) -> LeaveRequest:
    req = await _get_request_or_404(db, request_id)

    if req.status != LeaveStatus.PENDING_MANAGER:
        raise UnprocessableError(
            f"Request is '{req.status}', not pending manager approval"
        )

    prev = req.status.value
    req.status = LeaveStatus.PENDING_HR
    req.manager_id = manager_id
    req.manager_action_at = _NOW()
    req.manager_remarks = remarks
    await db.flush()
    final = await _get_request_or_404(db, request_id)
    await record_audit(
        db, table_name="leave_requests", record_id=request_id,
        action=AuditAction.UPDATE, performed_by_id=manager_id,
        before={"status": prev}, after={"status": final.status.value},
    )
    return final


async def hr_approve(
    db: AsyncSession,
    request_id: uuid.UUID,
    hr_id: uuid.UUID,
    remarks: str | None,
) -> LeaveRequest:
    req = await _get_request_or_404(db, request_id)

    # HR/Admin finalize: accept a request that is still pending the manager's step too
    # (a higher role can approve directly, skipping the manager stage).
    if req.status not in (LeaveStatus.PENDING_HR, LeaveStatus.PENDING_MANAGER):
        raise UnprocessableError(
            f"Request is '{req.status}', not awaiting approval"
        )

    # ── Deduct balance (with lock) ─────────────────────────────────────────────
    balance = await _get_or_create_balance(
        db,
        req.employee_id,
        req.leave_type_id,
        req.start_date.year,
    )
    available = await _available_days(balance)
    if available < req.days_requested:
        # Log the shortfall in remarks but still approve (HR discretion)
        shortfall_note = (
            f"[Balance shortfall: {available}/{req.days_requested} days available] "
        )
        req.hr_remarks = (shortfall_note + (remarks or "")).strip()
    else:
        req.hr_remarks = remarks

    before_status = req.status.value
    balance.used_days = float(balance.used_days) + float(req.days_requested)
    req.status = LeaveStatus.APPROVED
    req.hr_id = hr_id
    req.hr_action_at = _NOW()
    await db.flush()

    # Mark daily_attendance ON_LEAVE for each working day in leave range
    await _mark_on_leave(
        db, req.employee_id, req.start_date, req.end_date, is_half_day=req.is_half_day
    )

    audit = AuditLog(
        table_name="leave_requests",
        record_id=request_id,
        action=AuditAction.UPDATE,
        before_value={"status": before_status},
        after_value={"status": LeaveStatus.APPROVED.value, "hr_id": str(hr_id)},
        performed_by_id=hr_id,
    )
    db.add(audit)
    await db.flush()

    final_req = await _get_request_or_404(db, request_id)
    approver_name = (
        f"{final_req.approving_hr.first_name} {final_req.approving_hr.last_name}"
        if final_req.approving_hr else "HR"
    )

    from app.tasks.notifications import send_notification
    send_notification.delay(
        str(req.employee_id),
        "LEAVE_APPROVED",
        leave_type=req.leave_type.name if req.leave_type else "Leave",
        days=float(req.days_requested),
        start_date=str(req.start_date),
        approver=approver_name,
        reference_id=str(request_id),
        reference_type="leave_requests",
    )

    return final_req


async def reject(
    db: AsyncSession,
    request_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    is_hr: bool,
    remarks: str | None,
) -> LeaveRequest:
    """
    Manager or HR rejection.  HR can reject even at PENDING_MANAGER stage (override).
    Balance is NOT touched on rejection (was never deducted).
    """
    req = await _get_request_or_404(db, request_id)

    rejectable = {LeaveStatus.PENDING_MANAGER, LeaveStatus.PENDING_HR}
    if req.status not in rejectable:
        raise UnprocessableError(
            f"Cannot reject a request with status '{req.status}'"
        )

    if is_hr:
        req.hr_id = actor_id
        req.hr_action_at = _NOW()
        req.hr_remarks = remarks
    else:
        req.manager_id = actor_id
        req.manager_action_at = _NOW()
        req.manager_remarks = remarks

    prev = req.status.value
    req.status = LeaveStatus.REJECTED
    await db.flush()

    final_req = await _get_request_or_404(db, request_id)
    await record_audit(
        db, table_name="leave_requests", record_id=request_id,
        action=AuditAction.UPDATE, performed_by_id=actor_id,
        before={"status": prev}, after={"status": final_req.status.value},
    )

    from app.tasks.notifications import send_notification
    send_notification.delay(
        str(req.employee_id),
        "LEAVE_REJECTED",
        leave_type=req.leave_type.name if req.leave_type else "Leave",
        remarks=remarks or "No remarks provided",
        reference_id=str(request_id),
        reference_type="leave_requests",
    )

    return final_req


async def cancel(
    db: AsyncSession,
    request_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_privileged: bool = True,
) -> LeaveRequest:
    """
    Cancel/withdraw a leave request.
    - Employees (is_privileged=False) may cancel only their OWN request, and only while
      it is still awaiting approval (pending). HR/Admin may also cancel an APPROVED
      request (which restores the deducted balance).
    """
    req = await _get_request_or_404(db, request_id)

    if not is_privileged and req.employee_id != actor_id:
        raise ForbiddenError("You can only cancel your own leave request")

    cancellable = (
        {LeaveStatus.PENDING_MANAGER, LeaveStatus.PENDING_HR}
        if not is_privileged
        else {LeaveStatus.PENDING_MANAGER, LeaveStatus.PENDING_HR, LeaveStatus.APPROVED}
    )
    if req.status not in cancellable:
        raise UnprocessableError(
            f"Cannot cancel a request with status '{req.status}'"
        )

    was_approved = req.status == LeaveStatus.APPROVED
    prev = req.status.value

    req.status = LeaveStatus.CANCELLED
    await db.flush()
    await record_audit(
        db, table_name="leave_requests", record_id=request_id,
        action=AuditAction.UPDATE, performed_by_id=actor_id,
        before={"status": prev}, after={"status": LeaveStatus.CANCELLED.value},
    )

    if was_approved:
        # Restore the deducted days (lock the row to be safe)
        balance = await _get_or_create_balance(
            db,
            req.employee_id,
            req.leave_type_id,
            req.start_date.year,
        )
        balance.used_days = max(0.0, float(balance.used_days) - float(req.days_requested))
        await db.flush()

        # Revert daily_attendance rows from ON_LEAVE back to ABSENT
        await _revert_on_leave(db, req.employee_id, req.start_date, req.end_date)

    return await _get_request_or_404(db, request_id)


# ── Query helpers ─────────────────────────────────────────────────────────────

async def list_requests(
    db: AsyncSession,
    *,
    employee_id: uuid.UUID | None = None,
    employee_ids: list[uuid.UUID] | None = None,
    status: LeaveStatus | None = None,
    leave_type_id: uuid.UUID | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    per_page: int = 20,
    cursor: str | None = None,
) -> tuple[list[LeaveRequest], PaginationMeta]:
    stmt = (
        select(LeaveRequest)
        .where(LeaveRequest.deleted_at.is_(None))
        .options(
            selectinload(LeaveRequest.leave_type),
            selectinload(LeaveRequest.employee),
            selectinload(LeaveRequest.approving_manager),
            selectinload(LeaveRequest.approving_hr),
        )
    )
    if employee_id:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)
    # Restrict to a set of employees (e.g. a manager's department). An empty list
    # correctly yields no rows.
    if employee_ids is not None:
        stmt = stmt.where(LeaveRequest.employee_id.in_(employee_ids))
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    if leave_type_id:
        stmt = stmt.where(LeaveRequest.leave_type_id == leave_type_id)
    if from_date:
        stmt = stmt.where(LeaveRequest.start_date >= from_date)
    if to_date:
        stmt = stmt.where(LeaveRequest.end_date <= to_date)
    return await paginate(db, stmt, LeaveRequest, per_page, cursor)


async def get_request(db: AsyncSession, request_id: uuid.UUID) -> LeaveRequest:
    return await _get_request_or_404(db, request_id)


# ── Balance queries & management ──────────────────────────────────────────────

async def get_balances(
    db: AsyncSession,
    employee_id: uuid.UUID,
    year: int,
) -> list[LeaveBalance]:
    """
    Return a balance row for EVERY active leave type for the employee in `year`.

    Balances used to be created lazily only when an employee first applied for a
    given leave type, so a new employee saw no balances at all and, after applying,
    saw only the one category they'd used. To make the full allowance always visible
    (dashboard cards, apply-leave dropdown, HR view), we materialise a balance row for
    each active leave type that doesn't have one yet (allocated = days_per_year, 0 used).
    The insert is idempotent and race-safe via ON CONFLICT DO NOTHING on the
    (employee, leave_type, year) unique constraint.
    """
    types = await list_leave_types(db)

    existing_result = await db.execute(
        select(LeaveBalance.leave_type_id).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.year == year,
        )
    )
    existing_type_ids = set(existing_result.scalars().all())

    missing = [lt for lt in types if lt.id not in existing_type_ids]
    if missing:
        for lt in missing:
            await db.execute(
                pg_insert(LeaveBalance)
                .values(
                    employee_id=employee_id,
                    leave_type_id=lt.id,
                    year=year,
                    allocated_days=lt.days_per_year,
                    used_days=0,
                    carried_forward_days=0,
                )
                .on_conflict_do_nothing(
                    constraint="uq_leave_balance_employee_type_year"
                )
            )
        await db.flush()

    result = await db.execute(
        select(LeaveBalance)
        .join(LeaveType, LeaveBalance.leave_type_id == LeaveType.id)
        .where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.year == year,
        )
        .options(selectinload(LeaveBalance.leave_type))
        .order_by(LeaveType.name)
    )
    return list(result.scalars().all())


async def adjust_balance(
    db: AsyncSession, data: LeaveBalanceAdjustIn
) -> LeaveBalance:
    """HR upserts an employee's leave balance (set allocated/carried days)."""
    result = await db.execute(
        select(LeaveBalance)
        .where(
            LeaveBalance.employee_id == data.employee_id,
            LeaveBalance.leave_type_id == data.leave_type_id,
            LeaveBalance.year == data.year,
        )
        .with_for_update()
    )
    balance = result.scalar_one_or_none()

    if balance:
        balance.allocated_days = data.allocated_days
        balance.carried_forward_days = data.carried_forward_days
    else:
        balance = LeaveBalance(
            employee_id=data.employee_id,
            leave_type_id=data.leave_type_id,
            year=data.year,
            allocated_days=data.allocated_days,
            carried_forward_days=data.carried_forward_days,
            used_days=0,
        )
        db.add(balance)

    await db.flush()
    await db.refresh(balance)
    return balance
