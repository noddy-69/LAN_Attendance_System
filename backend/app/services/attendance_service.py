"""
Attendance Engine
=================
Implements the rules from CLAUDE.md verbatim:

    check_in      = first ENTRY event of the day
    check_out     = last EXIT event of the day
    work_hours    = check_out − check_in (minutes)
    late_threshold = branch.office_start_time + branch.grace_period_minutes
    is_late       = check_in > late_threshold
    late_minutes  = check_in − late_threshold  (if is_late)
    overtime      = max(0, work_hours − shift.required_minutes)

"Day" is defined by IST (UTC+5:30) calendar date, not UTC date.
"""
import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError, UnprocessableError
from app.models.attendance_event import AttendanceEvent, AttendanceSource, EventType
from app.models.attendance_proof import AttendanceProof, ProofType
from app.models.branch import Branch
from app.models.daily_attendance import AttendanceStatus, DailyAttendance
from app.models.device import Device
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveStatus
from app.models.shift import ShiftDefinition
from app.models.system import AuditAction, AuditLog, HolidayCalendar

IST = timezone(timedelta(hours=5, minutes=30))

# Fallback when employee has no shift assigned (8-hour day)
_DEFAULT_REQUIRED_MINUTES = 480

# HALF_DAY threshold: less than half the required minutes worked
_HALF_DAY_DENOMINATOR = 2


# ── Timezone helpers ──────────────────────────────────────────────────────────

def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_ist_date(utc_dt: datetime) -> date:
    return _ensure_utc(utc_dt).astimezone(IST).date()


def _ist_day_utc_bounds(ist_date: date) -> tuple[datetime, datetime]:
    """Return [start_utc, end_utc] covering the full IST calendar day."""
    start = datetime(ist_date.year, ist_date.month, ist_date.day, 0, 0, 0, tzinfo=IST)
    end   = datetime(ist_date.year, ist_date.month, ist_date.day, 23, 59, 59, 999999, tzinfo=IST)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _effective_ts(event: AttendanceEvent) -> datetime:
    """Use corrected_timestamp if set; otherwise raw_timestamp."""
    ts = event.corrected_timestamp or event.raw_timestamp
    return _ensure_utc(ts)


# ── Holiday / leave helpers ───────────────────────────────────────────────────

async def _is_holiday(db: AsyncSession, branch_id: uuid.UUID, d: date) -> bool:
    result = await db.execute(
        select(HolidayCalendar.id).where(
            HolidayCalendar.date == d,
            HolidayCalendar.deleted_at.is_(None),
            or_(
                HolidayCalendar.branch_id == branch_id,
                HolidayCalendar.branch_id.is_(None),   # national holidays
            ),
        )
    )
    return result.scalar_one_or_none() is not None


async def _is_on_approved_leave(
    db: AsyncSession, employee_id: uuid.UUID, d: date
) -> bool:
    result = await db.execute(
        select(LeaveRequest.id).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == LeaveStatus.APPROVED,
            LeaveRequest.start_date <= d,
            LeaveRequest.end_date >= d,
            LeaveRequest.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


# ── Status determination ──────────────────────────────────────────────────────

def _determine_status(
    check_in: datetime | None,
    check_out: datetime | None,
    work_minutes: int | None,
    is_late: bool,
    is_holiday: bool,
    is_weekend: bool,
    is_on_leave: bool,
    required_minutes: int,
) -> AttendanceStatus:
    # Priority: weekend > holiday > leave > work-time rules
    if is_weekend:
        return AttendanceStatus.WEEKEND
    if is_holiday:
        return AttendanceStatus.HOLIDAY
    if is_on_leave:
        return AttendanceStatus.ON_LEAVE
    if check_in is None:
        return AttendanceStatus.ABSENT
    if check_out is None:
        # Employee checked in but hasn't checked out yet
        return AttendanceStatus.LATE if is_late else AttendanceStatus.PRESENT
    # Both check_in and check_out exist
    half_threshold = required_minutes // _HALF_DAY_DENOMINATOR
    if work_minutes is not None and work_minutes < half_threshold:
        return AttendanceStatus.HALF_DAY
    return AttendanceStatus.LATE if is_late else AttendanceStatus.PRESENT


def _dominant_source(events: list[AttendanceEvent]) -> AttendanceSource:
    """Manual > biometric > selfie > face_recognition (most human-authoritative wins)."""
    sources = {e.source for e in events}
    if AttendanceSource.MANUAL in sources:
        return AttendanceSource.MANUAL
    if AttendanceSource.BIOMETRIC in sources:
        return AttendanceSource.BIOMETRIC
    if AttendanceSource.SELFIE in sources:
        return AttendanceSource.SELFIE
    return AttendanceSource.FACE_RECOGNITION


# ── Core engine ───────────────────────────────────────────────────────────────

async def recalculate_daily_attendance(
    db: AsyncSession,
    employee_id: uuid.UUID,
    ist_date: date,
) -> DailyAttendance:
    """
    Recompute and upsert daily_attendance for one employee/day.

    Idempotent — safe to call multiple times.  Does NOT overwrite notes (preserves
    any pending correction data stored there by the corrections workflow).
    """
    # ── Load employee (with branch + shift) ────────────────────────────────────
    emp_result = await db.execute(
        select(Employee)
        .where(Employee.id == employee_id, Employee.deleted_at.is_(None))
        .options(selectinload(Employee.branch), selectinload(Employee.shift))
    )
    employee = emp_result.scalar_one_or_none()
    if not employee:
        raise NotFoundError(f"Employee {employee_id} not found")

    branch: Branch = employee.branch
    shift: ShiftDefinition | None = employee.shift
    required_minutes = shift.required_minutes if shift else _DEFAULT_REQUIRED_MINUTES

    # ── Fetch all raw events within the IST day ───────────────────────────────
    utc_start, utc_end = _ist_day_utc_bounds(ist_date)
    ev_result = await db.execute(
        select(AttendanceEvent)
        .where(
            AttendanceEvent.employee_id == employee_id,
            AttendanceEvent.raw_timestamp >= utc_start,
            AttendanceEvent.raw_timestamp <= utc_end,
            AttendanceEvent.deleted_at.is_(None),
        )
        .order_by(AttendanceEvent.raw_timestamp)
    )
    events: list[AttendanceEvent] = list(ev_result.scalars().all())

    # ── First ENTRY / last EXIT (effective timestamps) ────────────────────────
    entries = [e for e in events if e.event_type == EventType.ENTRY]
    exits   = [e for e in events if e.event_type == EventType.EXIT]

    check_in  = _effective_ts(entries[0])  if entries else None
    check_out = _effective_ts(exits[-1])   if exits  else None

    # ── Late detection ────────────────────────────────────────────────────────
    # An employee is *flagged* late only if they check in after the grace window
    # (office_start + effective grace). But the late DURATION is measured from the
    # actual office start time — not from the end of grace. Grace decides whether it
    # counts as late; once it does, the minutes are counted from when work should have
    # begun. e.g. 09:00 start, 15-min grace, check-in 09:20 → late (past 09:15),
    # late_minutes = 20 (from 09:00), not 5.
    # Effective grace: the branch's own value if it set one, else the org-wide
    # default (system_policies['attendance.grace_period_minutes']).
    grace_minutes = await _resolve_grace_minutes(db, branch)
    office_start_ist = datetime.combine(ist_date, branch.office_start_time, tzinfo=IST)
    office_start_utc = office_start_ist.astimezone(timezone.utc)
    late_threshold_utc = (
        office_start_ist + timedelta(minutes=grace_minutes)
    ).astimezone(timezone.utc)

    is_late = bool(check_in and check_in > late_threshold_utc)
    late_minutes = (
        max(0, int((check_in - office_start_utc).total_seconds() / 60))
        if is_late and check_in else 0
    )

    # ── Work duration & overtime ──────────────────────────────────────────────
    work_minutes: int | None = None
    overtime_minutes = 0
    if check_in and check_out:
        work_minutes = max(0, int((check_out - check_in).total_seconds() / 60))
        overtime_minutes = max(0, work_minutes - required_minutes)

    # ── Contextual flags — run holiday + leave checks in parallel ─────────────
    # Sunday (6) is always a weekly off. Saturday (5) is off only when the admin/HR
    # policy attendance.saturday_off is true (the default).
    weekday = ist_date.weekday()
    if weekday == 6:
        is_weekend = True
    elif weekday == 5:
        is_weekend = await _saturday_is_off(db)
    else:
        is_weekend = False
    is_holiday, is_on_leave = await asyncio.gather(
        _is_holiday(db, branch.id, ist_date),
        _is_on_approved_leave(db, employee_id, ist_date),
    )

    status = _determine_status(
        check_in, check_out, work_minutes, is_late,
        is_holiday, is_weekend, is_on_leave, required_minutes,
    )
    source = _dominant_source(events) if events else AttendanceSource.MANUAL

    # ── Upsert — never overwrite 'notes' (correction data lives there) ────────
    row_values = dict(
        employee_id=employee_id,
        date=ist_date,
        check_in=check_in,
        check_out=check_out,
        work_minutes=work_minutes,
        overtime_minutes=overtime_minutes,
        late_minutes=late_minutes,
        is_late=is_late,
        status=status,
        source=source,
    )
    upsert = pg_insert(DailyAttendance).values(**row_values)
    upsert = upsert.on_conflict_do_update(
        constraint="uq_daily_attendance_employee_date",
        set_={
            "check_in":         upsert.excluded.check_in,
            "check_out":        upsert.excluded.check_out,
            "work_minutes":     upsert.excluded.work_minutes,
            "overtime_minutes": upsert.excluded.overtime_minutes,
            "late_minutes":     upsert.excluded.late_minutes,
            "is_late":          upsert.excluded.is_late,
            "status":           upsert.excluded.status,
            "source":           upsert.excluded.source,
            # 'notes' deliberately omitted — preserves pending corrections
        },
    )
    await db.execute(upsert)
    await db.flush()

    # populate_existing=True forces SQLAlchemy to overwrite any stale identity-map
    # entry with a fresh DB read.  Without this, the Core upsert updates the DB row
    # but the ORM object (if previously loaded) retains old values — including the
    # expired `updated_at` column which triggers MissingGreenlet on access.
    result = await db.execute(
        select(DailyAttendance)
        .where(
            DailyAttendance.employee_id == employee_id,
            DailyAttendance.date == ist_date,
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def process_event(
    db: AsyncSession,
    *,
    employee_id: uuid.UUID,
    branch_id: uuid.UUID,
    event_type: EventType,
    source: AttendanceSource,
    raw_timestamp: datetime,
    device_id: uuid.UUID | None = None,
    confidence_score: float | None = None,
    biometric_uid: str | None = None,
    proof_storage_path: str | None = None,
) -> tuple[AttendanceEvent, DailyAttendance]:
    """
    Persist one attendance event and trigger full daily recalculation.

    Enforces two guards before persisting:
      1. Cooldown — same event_type within ATTENDANCE_COOLDOWN_SECONDS is rejected.
      2. Sequence validation — consecutive ENTRYs without an intervening EXIT are rejected.

    Returns (event, daily_attendance).
    """
    raw_timestamp = _ensure_utc(raw_timestamp)

    # ── Guard 0: Device must be registered (FK would otherwise 500 on flush) ──
    if device_id is not None:
        dev_result = await db.execute(
            select(Device).where(
                Device.id == device_id,
                Device.deleted_at.is_(None),
            )
        )
        device = dev_result.scalar_one_or_none()
        if device is None:
            raise NotFoundError(f"Device {device_id} is not registered")
        # Touch heartbeat so the admin dashboard shows the camera as live.
        device.last_heartbeat = datetime.now(timezone.utc)

    # ── Guard 1: Cooldown ─────────────────────────────────────────────────────
    cooldown_seconds = settings.ATTENDANCE_COOLDOWN_SECONDS
    cutoff = raw_timestamp - timedelta(seconds=cooldown_seconds)
    dup_result = await db.execute(
        select(AttendanceEvent.id).where(
            AttendanceEvent.employee_id == employee_id,
            AttendanceEvent.event_type == event_type,
            AttendanceEvent.raw_timestamp >= cutoff,
            AttendanceEvent.raw_timestamp <= raw_timestamp,
            AttendanceEvent.deleted_at.is_(None),
        ).limit(1)
    )
    if dup_result.scalar_one_or_none():
        raise UnprocessableError(
            f"Cooldown active: a {event_type.value} event was already recorded "
            f"within the last {cooldown_seconds // 60} minutes for this employee. "
            "Wait for the cooldown window to pass before recording another."
        )

    # ── Guard 2: Sequence — repeat same-day ENTRY is an idempotent no-op ──────
    # The first ENTRY of the IST day is the check-in. A later ENTRY with no EXIT in
    # between is normal for a single entry-only camera (the person is re-detected all
    # day) — so instead of erroring, we just return the day's existing record without
    # creating a duplicate event. (Cross-day is fine: this query is scoped to today, so
    # a fresh day's first ENTRY always proceeds. EXIT events are never blocked here.)
    if event_type == EventType.ENTRY:
        ist_date = _to_ist_date(raw_timestamp)
        utc_start, _ = _ist_day_utc_bounds(ist_date)
        last_result = await db.execute(
            select(AttendanceEvent).where(
                AttendanceEvent.employee_id == employee_id,
                AttendanceEvent.raw_timestamp >= utc_start,
                AttendanceEvent.raw_timestamp < raw_timestamp,
                AttendanceEvent.deleted_at.is_(None),
            ).order_by(AttendanceEvent.raw_timestamp.desc()).limit(1)
        )
        last_event = last_result.scalar_one_or_none()
        if last_event is not None and last_event.event_type == EventType.ENTRY:
            existing = await get_daily(db, employee_id, ist_date)
            if existing is None:
                existing = await recalculate_daily_attendance(db, employee_id, ist_date)
            return last_event, existing

    event = AttendanceEvent(
        employee_id=employee_id,
        branch_id=branch_id,
        device_id=device_id,
        event_type=event_type,
        source=source,
        raw_timestamp=raw_timestamp,
        confidence_score=confidence_score,
        biometric_uid=biometric_uid,
    )
    db.add(event)
    await db.flush()

    if proof_storage_path:
        proof = AttendanceProof(
            attendance_event_id=event.id,
            employee_id=employee_id,
            proof_type=(
                ProofType.ENTRY_IMAGE
                if event_type == EventType.ENTRY
                else ProofType.EXIT_IMAGE
            ),
            storage_path=proof_storage_path,
            captured_at=raw_timestamp,
        )
        db.add(proof)
        await db.flush()

    ist_date = _to_ist_date(raw_timestamp)
    daily = await recalculate_daily_attendance(db, employee_id, ist_date)

    # No "attendance marked" notification on a normal check-in — that would email
    # every employee every working day. Employees see their check-in confirmation in
    # the portal immediately; we only push notifications for exceptions (late arrival
    # here, and ABSENT_ALERT from the nightly materialization task).
    #
    # LATE_ARRIVAL fires only on the ENTRY (the arrival) — not again on the EXIT of the
    # same day, which would recompute the same is_late and send a duplicate. The
    # ENTRY-after-ENTRY no-op guard above already prevents a second same-day ENTRY.
    from app.tasks.notifications import send_notification
    if event_type == EventType.ENTRY and daily.is_late and daily.late_minutes:
        send_notification.delay(
            str(employee_id),
            "LATE_ARRIVAL",
            late_minutes=daily.late_minutes,
            reference_id=str(daily.id),
            reference_type="daily_attendance",
        )

    return event, daily


async def _get_policy_value(db: AsyncSession, key: str) -> str | None:
    """Read a single system_policies value (raw JSON-serialised string), or None."""
    from app.models.system import SystemPolicy
    res = await db.execute(
        select(SystemPolicy.value).where(
            SystemPolicy.key == key,
            SystemPolicy.deleted_at.is_(None),
        )
    )
    return res.scalar_one_or_none()


async def _saturday_is_off(db: AsyncSession) -> bool:
    """Whether Saturday counts as a weekly off. Policy attendance.saturday_off (default True)."""
    raw = await _get_policy_value(db, "attendance.saturday_off")
    if raw is None:
        return True
    try:
        return bool(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return raw.strip().lower() in ("1", "true", "yes")


async def _resolve_grace_minutes(db: AsyncSession, branch: Branch) -> int:
    """
    Resolve the effective late-grace (minutes) for a branch.

    A branch may set its own ``grace_period_minutes`` as an explicit override
    (0 = truly no grace). When it leaves that unset (NULL), the org-wide default
    from ``system_policies['attendance.grace_period_minutes']`` applies, falling
    back to ``settings.DEFAULT_GRACE_PERIOD_MINUTES`` if the policy is missing.
    """
    if branch.grace_period_minutes is not None:
        return branch.grace_period_minutes

    default = settings.DEFAULT_GRACE_PERIOD_MINUTES
    raw = await _get_policy_value(db, "attendance.grace_period_minutes")
    if raw is not None:
        try:
            return int(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
    return default


async def get_selfie_config(db: AsyncSession) -> dict:
    """
    Resolve the self-service selfie check-in policy:
      • enabled   — system_policies['selfie.enabled'] (default True)
      • threshold — reuses system_policies['face.confidence_threshold']
                    (falls back to settings.FACE_CONFIDENCE_THRESHOLD)
    """
    enabled = True
    raw_enabled = await _get_policy_value(db, "selfie.enabled")
    if raw_enabled is not None:
        try:
            enabled = bool(json.loads(raw_enabled))
        except (json.JSONDecodeError, TypeError):
            enabled = raw_enabled.strip().lower() in ("1", "true", "yes")

    threshold = settings.FACE_CONFIDENCE_THRESHOLD
    raw_thr = await _get_policy_value(db, "face.confidence_threshold")
    if raw_thr is not None:
        try:
            threshold = float(json.loads(raw_thr))
        except (json.JSONDecodeError, TypeError, ValueError):
            try:
                threshold = float(raw_thr)
            except ValueError:
                pass
    return {"enabled": enabled, "threshold": threshold}


async def process_selfie_event(
    db: AsyncSession,
    *,
    employee_id: uuid.UUID,
    branch_id: uuid.UUID,
    event_type: EventType,
    raw_timestamp: datetime,
    confidence_score: float,
    proof_storage_path: str | None,
    from_lan: bool,
    ip_address: str | None,
) -> tuple[AttendanceEvent, DailyAttendance]:
    """
    Record a self-service selfie attendance event (source=SELFIE).

    Adds two selfie-specific guards on top of process_event:
      • EXIT requires an existing ENTRY earlier the same IST day.
    Writes a flag-and-audit AuditLog row capturing the source IP, the LAN
    verdict, and the match similarity (off-LAN check-ins are recorded, not
    blocked).
    """
    raw_timestamp = _ensure_utc(raw_timestamp)

    if event_type == EventType.EXIT:
        ist_date = _to_ist_date(raw_timestamp)
        utc_start, _ = _ist_day_utc_bounds(ist_date)
        entry_res = await db.execute(
            select(AttendanceEvent.id).where(
                AttendanceEvent.employee_id == employee_id,
                AttendanceEvent.event_type == EventType.ENTRY,
                AttendanceEvent.raw_timestamp >= utc_start,
                AttendanceEvent.raw_timestamp <= raw_timestamp,
                AttendanceEvent.deleted_at.is_(None),
            ).limit(1)
        )
        if entry_res.scalar_one_or_none() is None:
            raise UnprocessableError(
                "You haven't checked in today yet — check in before checking out."
            )

    event, daily = await process_event(
        db,
        employee_id=employee_id,
        branch_id=branch_id,
        event_type=event_type,
        source=AttendanceSource.SELFIE,
        raw_timestamp=raw_timestamp,
        confidence_score=confidence_score,
        proof_storage_path=proof_storage_path,
    )

    # Flag & audit — record the LAN verdict and similarity without blocking.
    audit = AuditLog(
        table_name="attendance_events",
        record_id=event.id,
        action=AuditAction.CREATE,
        before_value=None,
        after_value={
            "method": "selfie",
            "event_type": event_type.value,
            "from_office_lan": from_lan,
            "similarity": round(float(confidence_score), 4),
        },
        performed_by_id=employee_id,
        ip_address=ip_address,
    )
    db.add(audit)
    await db.flush()
    if not from_lan:
        import logging
        logging.getLogger(__name__).warning(
            "Selfie check-in from OUTSIDE office LAN: employee=%s ip=%s",
            employee_id, ip_address,
        )
    return event, daily


async def process_biometric_event(
    db: AsyncSession,
    sn: str,
    uid: str,
    device_time_str: str,
    state_str: str,
) -> tuple[AttendanceEvent, DailyAttendance]:
    """
    Parse a ZKTeco K40 ADMS payload and process the attendance event.

    Device timestamps are in device local time (IST for Indian offices).
    Mapping: state == BIOMETRIC_CHECKIN_STATE → ENTRY, else → EXIT.
    """
    # Lookup device by serial number. Optional by default, but when
    # BIOMETRIC_REQUIRE_REGISTERED_DEVICE is set the serial must match a
    # registered device — blunts spoofed pushes from unknown sources.
    dev_result = await db.execute(
        select(Device).where(
            Device.device_uid == sn,
            Device.deleted_at.is_(None),
        )
    )
    device = dev_result.scalar_one_or_none()
    if device is None and settings.BIOMETRIC_REQUIRE_REGISTERED_DEVICE:
        raise ForbiddenError(
            f"Biometric device '{sn}' is not registered. "
            "Register it in the Admin portal before it can push events."
        )

    # Touch the device heartbeat so the dashboard reflects recent activity.
    if device is not None:
        device.last_heartbeat = datetime.now(timezone.utc)

    # Find employee by biometric UID
    emp_result = await db.execute(
        select(Employee).where(
            Employee.biometric_uid == uid,
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
    )
    employee = emp_result.scalar_one_or_none()
    if not employee:
        raise NotFoundError(
            f"No active employee with biometric_uid '{uid}'. "
            "Register the employee on the biometric device first."
        )

    # Device time is device-local (IST) → convert to UTC
    device_naive = datetime.strptime(device_time_str, "%Y-%m-%d %H:%M:%S")
    utc_dt = device_naive.replace(tzinfo=IST).astimezone(timezone.utc)

    event_type = (
        EventType.ENTRY
        if int(state_str) == settings.BIOMETRIC_CHECKIN_STATE
        else EventType.EXIT
    )
    branch_id = device.branch_id if device else employee.branch_id

    return await process_event(
        db,
        employee_id=employee.id,
        branch_id=branch_id,
        event_type=event_type,
        source=AttendanceSource.BIOMETRIC,
        raw_timestamp=utc_dt,
        device_id=device.id if device else None,
        biometric_uid=uid,
    )


# ── Daily attendance queries ──────────────────────────────────────────────────

async def get_daily(
    db: AsyncSession,
    employee_id: uuid.UUID,
    ist_date: date,
) -> DailyAttendance | None:
    result = await db.execute(
        select(DailyAttendance).where(
            DailyAttendance.employee_id == employee_id,
            DailyAttendance.date == ist_date,
            DailyAttendance.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_daily(
    db: AsyncSession,
    *,
    employee_id: uuid.UUID | None = None,
    employee_ids: list[uuid.UUID] | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    status: AttendanceStatus | None = None,
    per_page: int = 30,
    cursor: str | None = None,
) -> tuple[list[DailyAttendance], "PaginationMeta"]:
    from sqlalchemy import func as _func
    from app.models.role import Role
    from app.schemas.common import PaginationMeta

    stmt = select(DailyAttendance).where(DailyAttendance.deleted_at.is_(None))
    # Admin + service accounts aren't attendance-tracked, so never show their rows.
    stmt = stmt.where(
        ~DailyAttendance.employee_id.in_(
            select(Employee.id).where(Employee.role.has(Role.name.in_(["admin", "service"])))
        )
    )
    if employee_id:
        stmt = stmt.where(DailyAttendance.employee_id == employee_id)
    # Restrict to a set of employees (e.g. a manager's department); [] yields no rows.
    if employee_ids is not None:
        stmt = stmt.where(DailyAttendance.employee_id.in_(employee_ids))
    if from_date:
        stmt = stmt.where(DailyAttendance.date >= from_date)
    if to_date:
        stmt = stmt.where(DailyAttendance.date <= to_date)
    if status:
        stmt = stmt.where(DailyAttendance.status == status)

    # Order by attendance DATE (most recent first), not DB insertion order — so a
    # date-ranged view is chronological and the newest days are never pushed past the
    # row cap. (The generic created_at cursor pagination ordered by insert time, which
    # scattered a day's rows across pages and could truncate recent days.)
    total = (await db.execute(select(_func.count()).select_from(stmt.subquery()))).scalar_one()
    ordered = stmt.order_by(
        DailyAttendance.date.desc(), DailyAttendance.created_at.desc()
    ).limit(per_page)
    rows = list((await db.execute(ordered)).scalars().all())

    return rows, PaginationMeta(
        total=total,
        page=1,
        per_page=per_page,
        has_next=total > len(rows),
        next_cursor=None,
    )


async def manual_override(
    db: AsyncSession,
    employee_id: uuid.UUID,
    ist_date: date,
    check_in: datetime | None,
    check_out: datetime | None,
    status_override: AttendanceStatus | None,
    notes: str | None,
    actor_id: uuid.UUID,
) -> DailyAttendance:
    """
    HR direct override: optionally set corrected_timestamp on existing events,
    or inject manual events, then recalculate. Writes an audit_logs row (before →
    after) attributed to actor_id, so every manual attendance change is traceable.
    """
    # Capture the before-state for the audit trail (may be None if no record yet).
    before = await get_daily(db, employee_id, ist_date)
    before_check_in = before.check_in if before else None
    before_check_out = before.check_out if before else None
    before_status = before.status.value if before and before.status else None

    utc_start, utc_end = _ist_day_utc_bounds(ist_date)

    # Fetch existing events for this day
    ev_result = await db.execute(
        select(AttendanceEvent)
        .where(
            AttendanceEvent.employee_id == employee_id,
            AttendanceEvent.raw_timestamp >= utc_start,
            AttendanceEvent.raw_timestamp <= utc_end,
            AttendanceEvent.deleted_at.is_(None),
        )
        .order_by(AttendanceEvent.raw_timestamp)
    )
    events = list(ev_result.scalars().all())

    # Find employee branch for new manual events
    emp_result = await db.execute(
        select(Employee.branch_id).where(Employee.id == employee_id)
    )
    branch_id = emp_result.scalar_one()

    # Apply check_in override
    if check_in is not None:
        check_in_utc = _ensure_utc(check_in)
        entries = [e for e in events if e.event_type == EventType.ENTRY]
        if entries:
            entries[0].corrected_timestamp = check_in_utc
        else:
            # Create a manual ENTRY event
            manual_entry = AttendanceEvent(
                employee_id=employee_id,
                branch_id=branch_id,
                event_type=EventType.ENTRY,
                source=AttendanceSource.MANUAL,
                raw_timestamp=check_in_utc,
            )
            db.add(manual_entry)

    # Apply check_out override
    if check_out is not None:
        check_out_utc = _ensure_utc(check_out)
        exits = [e for e in events if e.event_type == EventType.EXIT]
        if exits:
            exits[-1].corrected_timestamp = check_out_utc
        else:
            manual_exit = AttendanceEvent(
                employee_id=employee_id,
                branch_id=branch_id,
                event_type=EventType.EXIT,
                source=AttendanceSource.MANUAL,
                raw_timestamp=check_out_utc,
            )
            db.add(manual_exit)

    await db.flush()

    daily = await recalculate_daily_attendance(db, employee_id, ist_date)

    # Apply status override and notes AFTER recalculation.
    # populate_existing=True already returned a fresh object from recalculate_,
    # so direct attribute writes here are safe.
    if status_override is not None:
        daily.status = status_override
    if notes is not None:
        daily.notes = notes

    await db.flush()

    # Re-fetch once more so updated_at reflects the flush above.
    result2 = await db.execute(
        select(DailyAttendance)
        .where(DailyAttendance.id == daily.id)
        .execution_options(populate_existing=True)
    )
    final = result2.scalar_one()

    # Audit trail — record who changed the attendance and what changed.
    audit = AuditLog(
        table_name="daily_attendance",
        record_id=final.id,
        action=AuditAction.UPDATE,
        before_value={
            "check_in": before_check_in.isoformat() if before_check_in else None,
            "check_out": before_check_out.isoformat() if before_check_out else None,
            "status": before_status,
        },
        after_value={
            "check_in": final.check_in.isoformat() if final.check_in else None,
            "check_out": final.check_out.isoformat() if final.check_out else None,
            "status": final.status.value if final.status else None,
        },
        performed_by_id=actor_id,
    )
    db.add(audit)
    await db.flush()

    return final


# ── Corrections workflow ──────────────────────────────────────────────────────

_CORR_KEY = "correction"


def _parse_correction(daily: DailyAttendance) -> dict | None:
    """Extract the correction dict from daily_attendance.notes, or None."""
    if not daily.notes:
        return None
    try:
        data = json.loads(daily.notes)
        return data.get(_CORR_KEY)
    except (json.JSONDecodeError, AttributeError):
        return None


def _set_correction(daily: DailyAttendance, corr: dict | None) -> None:
    """Serialize correction dict back into daily_attendance.notes."""
    if corr is None:
        daily.notes = None
    else:
        daily.notes = json.dumps({_CORR_KEY: corr})


async def submit_correction(
    db: AsyncSession,
    employee_id: uuid.UUID,
    ist_date: date,
    requested_check_in: datetime | None,
    requested_check_out: datetime | None,
    reason: str,
    proof_path: str | None = None,
) -> DailyAttendance:
    """Employee submits a correction request for their own record."""
    # Ensure daily record exists (create if missing)
    daily = await get_daily(db, employee_id, ist_date)
    if not daily:
        daily = await recalculate_daily_attendance(db, employee_id, ist_date)

    if _parse_correction(daily) is not None:
        raise UnprocessableError(
            "A correction request already exists for this day. "
            "Wait for it to be actioned before submitting another."
        )

    corr = {
        "requested_by": str(employee_id),
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "requested_check_in":  _ensure_utc(requested_check_in).isoformat() if requested_check_in else None,
        "requested_check_out": _ensure_utc(requested_check_out).isoformat() if requested_check_out else None,
        "reason": reason,
        "proof_path": proof_path,   # optional supporting evidence (MinIO object key)
        "correction_status": "pending",
        "actioned_by": None,
        "actioned_at": None,
        "remarks": None,
    }
    # NOTE: the day keeps its real computed status (e.g. HALF_DAY / ABSENT) while the
    # correction is pending — the request is tracked in `notes`, not by overwriting the
    # status. Only when the correction is APPROVED does the status change (via the
    # requested times + recalculation). Corrections are surfaced by list_corrections()
    # (which reads the notes), the Corrections tab, and the employee's own page.
    _set_correction(daily, corr)
    await db.flush()
    return daily


async def attach_correction_proof(
    db: AsyncSession,
    daily_id: uuid.UUID,
    employee_id: uuid.UUID,
    proof_path: str,
) -> DailyAttendance:
    """Attach an uploaded proof to the caller's own pending correction request."""
    result = await db.execute(
        select(DailyAttendance).where(
            DailyAttendance.id == daily_id,
            DailyAttendance.deleted_at.is_(None),
        )
    )
    daily = result.scalar_one_or_none()
    if not daily:
        raise NotFoundError(f"Daily attendance record {daily_id} not found")
    if daily.employee_id != employee_id:
        raise ForbiddenError("You can only attach proof to your own correction request")

    corr = _parse_correction(daily)
    if not corr or corr.get("correction_status") != "pending":
        raise UnprocessableError("No pending correction on this record to attach proof to")

    corr["proof_path"] = proof_path
    _set_correction(daily, corr)
    await db.flush()
    return daily


async def cancel_correction(
    db: AsyncSession,
    daily_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_privileged: bool,
) -> DailyAttendance:
    """
    Withdraw a not-yet-approved correction request. Removes the correction data and
    recomputes the day's real status (so a day stuck at PENDING_CORRECTION reverts to
    its computed status, e.g. HALF_DAY / ABSENT). Employees may cancel only their own.
    """
    result = await db.execute(
        select(DailyAttendance).where(
            DailyAttendance.id == daily_id,
            DailyAttendance.deleted_at.is_(None),
        )
    )
    daily = result.scalar_one_or_none()
    if not daily:
        raise NotFoundError(f"Daily attendance record {daily_id} not found")

    corr = _parse_correction(daily)
    if not corr:
        raise UnprocessableError("No correction request on this record")
    if not is_privileged and daily.employee_id != actor_id:
        raise ForbiddenError("You can only cancel your own correction request")
    if corr.get("correction_status") not in ("pending", "pending_hr"):
        raise UnprocessableError(
            "Only a correction still awaiting approval can be cancelled"
        )

    employee_id_saved = daily.employee_id
    ist_date_saved = daily.date
    _set_correction(daily, None)   # clears daily.notes
    await db.flush()
    # Recompute the real status from events (PENDING_CORRECTION → HALF_DAY/PRESENT/ABSENT).
    return await recalculate_daily_attendance(db, employee_id_saved, ist_date_saved)


async def action_correction(
    db: AsyncSession,
    daily_id: uuid.UUID,
    actor_id: uuid.UUID,
    approve: bool,
    remarks: str | None,
) -> DailyAttendance:
    """Manager or HR approves/rejects a pending correction."""
    result = await db.execute(
        select(DailyAttendance).where(
            DailyAttendance.id == daily_id,
            DailyAttendance.deleted_at.is_(None),
        )
    )
    daily = result.scalar_one_or_none()
    if not daily:
        raise NotFoundError(f"Daily attendance record {daily_id} not found")

    corr = _parse_correction(daily)
    if not corr or corr.get("correction_status") != "pending":
        raise UnprocessableError("No pending correction on this record")

    corr["actioned_by"] = str(actor_id)
    corr["actioned_at"] = datetime.now(timezone.utc).isoformat()
    corr["remarks"] = remarks
    corr["correction_status"] = "approved" if approve else "rejected"
    _set_correction(daily, corr)

    # Capture before daily gets replaced
    employee_id_saved = daily.employee_id
    ist_date_saved = daily.date

    if approve:
        check_in_str  = corr.get("requested_check_in")
        check_out_str = corr.get("requested_check_out")
        daily = await manual_override(
            db,
            employee_id=employee_id_saved,
            ist_date=ist_date_saved,
            check_in=datetime.fromisoformat(check_in_str)   if check_in_str  else None,
            check_out=datetime.fromisoformat(check_out_str) if check_out_str else None,
            status_override=None,
            notes=None,
            actor_id=actor_id,
        )
        # manual_override already called recalculate_daily_attendance with populate_existing,
        # so `daily` now has the correct computed status (e.g. LATE / PRESENT).
    else:
        daily = await recalculate_daily_attendance(db, employee_id_saved, ist_date_saved)

    # Persist the updated correction metadata onto the (now fresh) daily object.
    _set_correction(daily, corr)
    await db.flush()

    # One final fresh read to ensure updated_at is current.
    result3 = await db.execute(
        select(DailyAttendance)
        .where(DailyAttendance.id == daily.id)
        .execution_options(populate_existing=True)
    )
    return result3.scalar_one()


async def manager_approve_correction(
    db: AsyncSession,
    daily_id: uuid.UUID,
    manager_id: uuid.UUID,
    remarks: str | None,
) -> DailyAttendance:
    """
    First-level approval: manager reviews the correction request.
    Transitions correction_status: "pending" → "pending_hr".
    Does NOT apply the requested times yet; HR must approve next.
    """
    result = await db.execute(
        select(DailyAttendance).where(
            DailyAttendance.id == daily_id,
            DailyAttendance.deleted_at.is_(None),
        )
    )
    daily = result.scalar_one_or_none()
    if not daily:
        raise NotFoundError(f"Daily attendance record {daily_id} not found")

    corr = _parse_correction(daily)
    if not corr or corr.get("correction_status") != "pending":
        raise UnprocessableError(
            "No pending correction on this record "
            "(expected correction_status='pending')"
        )

    if str(manager_id) == corr.get("requested_by"):
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Managers cannot approve their own correction requests")

    corr["manager_actioned_by"] = str(manager_id)
    corr["manager_actioned_at"] = datetime.now(timezone.utc).isoformat()
    corr["manager_remarks"] = remarks
    corr["correction_status"] = "pending_hr"
    _set_correction(daily, corr)
    await db.flush()

    result2 = await db.execute(
        select(DailyAttendance)
        .where(DailyAttendance.id == daily_id)
        .execution_options(populate_existing=True)
    )
    return result2.scalar_one()


async def hr_approve_correction(
    db: AsyncSession,
    daily_id: uuid.UUID,
    hr_id: uuid.UUID,
    remarks: str | None,
) -> DailyAttendance:
    """
    Second-level approval: HR approves and applies the requested correction.
    Transitions correction_status: "pending_hr" → "approved".
    Calls manual_override() to update check_in/check_out and recalculate status.
    """
    result = await db.execute(
        select(DailyAttendance).where(
            DailyAttendance.id == daily_id,
            DailyAttendance.deleted_at.is_(None),
        )
    )
    daily = result.scalar_one_or_none()
    if not daily:
        raise NotFoundError(f"Daily attendance record {daily_id} not found")

    corr = _parse_correction(daily)
    # HR/Admin finalize: accept a correction still at the manager stage ("pending") too,
    # so a higher role can approve directly, skipping the manager's review.
    if not corr or corr.get("correction_status") not in ("pending", "pending_hr"):
        raise UnprocessableError(
            "Correction is not awaiting approval "
            "(expected correction_status 'pending' or 'pending_hr')"
        )

    if str(hr_id) == corr.get("requested_by"):
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("You cannot approve your own correction request")

    corr["hr_actioned_by"] = str(hr_id)
    corr["hr_actioned_at"] = datetime.now(timezone.utc).isoformat()
    corr["hr_remarks"] = remarks
    # Mirror into legacy fields so _correction_out remains backward-compatible
    corr["actioned_by"] = str(hr_id)
    corr["actioned_at"] = corr["hr_actioned_at"]
    corr["remarks"] = remarks
    corr["correction_status"] = "approved"

    employee_id_saved = daily.employee_id
    ist_date_saved = daily.date
    check_in_str  = corr.get("requested_check_in")
    check_out_str = corr.get("requested_check_out")

    # manual_override writes the daily_attendance audit row (before → after, actor).
    daily = await manual_override(
        db,
        employee_id=employee_id_saved,
        ist_date=ist_date_saved,
        check_in=datetime.fromisoformat(check_in_str)   if check_in_str  else None,
        check_out=datetime.fromisoformat(check_out_str) if check_out_str else None,
        status_override=None,
        notes=None,
        actor_id=hr_id,
    )

    _set_correction(daily, corr)
    await db.flush()

    result3 = await db.execute(
        select(DailyAttendance)
        .where(DailyAttendance.id == daily.id)
        .execution_options(populate_existing=True)
    )
    final = result3.scalar_one()

    from app.tasks.notifications import send_notification
    send_notification.delay(
        str(employee_id_saved),
        "CORRECTION_STATUS",
        date=str(ist_date_saved),
        status="approved",
        remarks=remarks or "",
        reference_id=str(final.id),
        reference_type="daily_attendance",
    )

    return final


async def list_corrections(
    db: AsyncSession,
    employee_id: uuid.UUID | None = None,
    employee_ids: list[uuid.UUID] | None = None,
) -> list[DailyAttendance]:
    """
    Return all daily records that carry a correction request (any correction_status),
    identified by the correction data stored in `notes` — independent of the day's
    attendance status, which now stays at its real computed value while pending.
    """
    stmt = select(DailyAttendance).where(
        DailyAttendance.notes.isnot(None),
        DailyAttendance.deleted_at.is_(None),
    )
    if employee_id:
        stmt = stmt.where(DailyAttendance.employee_id == employee_id)
    # Restrict to a set of employees (e.g. a manager's department); [] yields no rows.
    if employee_ids is not None:
        stmt = stmt.where(DailyAttendance.employee_id.in_(employee_ids))
    stmt = stmt.order_by(DailyAttendance.date.desc())
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    # Keep only rows whose notes actually contain a correction record.
    return [r for r in rows if _parse_correction(r) is not None]


# ── Proof queries ─────────────────────────────────────────────────────────────

async def get_proofs_for_day(
    db: AsyncSession,
    employee_id: uuid.UUID,
    ist_date: date,
) -> list[AttendanceProof]:
    """Return all proof frames for one employee/day."""
    utc_start, utc_end = _ist_day_utc_bounds(ist_date)
    result = await db.execute(
        select(AttendanceProof)
        .join(
            AttendanceEvent,
            AttendanceProof.attendance_event_id == AttendanceEvent.id,
        )
        .where(
            AttendanceProof.employee_id == employee_id,
            AttendanceEvent.raw_timestamp >= utc_start,
            AttendanceEvent.raw_timestamp <= utc_end,
            AttendanceProof.deleted_at.is_(None),
        )
        .order_by(AttendanceProof.captured_at)
    )
    return list(result.scalars().all())


# ── Event list queries ────────────────────────────────────────────────────────

async def list_events(
    db: AsyncSession,
    *,
    employee_id: uuid.UUID | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    per_page: int = 50,
    cursor: str | None = None,
) -> tuple[list[AttendanceEvent], "PaginationMeta"]:
    from app.utils.pagination import paginate

    stmt = select(AttendanceEvent).where(AttendanceEvent.deleted_at.is_(None))
    if employee_id:
        stmt = stmt.where(AttendanceEvent.employee_id == employee_id)
    if from_dt:
        stmt = stmt.where(AttendanceEvent.raw_timestamp >= _ensure_utc(from_dt))
    if to_dt:
        stmt = stmt.where(AttendanceEvent.raw_timestamp <= _ensure_utc(to_dt))

    return await paginate(db, stmt, AttendanceEvent, per_page, cursor)
