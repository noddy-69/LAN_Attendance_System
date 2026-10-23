import ipaddress
import math
import uuid
from datetime import date, datetime, timezone

import httpx
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenError, NotFoundError, UnprocessableError
from app.core.rbac import is_hr_tier, require_hr_tier_final_approval, require_permission
from app.core.scoping import assert_can_act_on, visible_employee_ids
from app.models.system import AuditAction
from app.services.audit_service import record_audit
from app.core.security import get_current_user
from app.models.attendance_event import AttendanceSource, EventType
from app.models.attendance_proof import AttendanceProof
from app.models.daily_attendance import AttendanceStatus
from app.models.employee import Employee
from app.services import face_service
from app.schemas.attendance import (
    AttendanceEventOut,
    BiometricEventIn,
    CameraEventIn,
    CorrectionActionIn,
    CorrectionOut,
    CorrectionRequestIn,
    DailyAttendanceOut,
    DailyOverrideIn,
    ManualEventIn,
    ProofOut,
)
from app.schemas.common import ApiResponse
from app.services import attendance_service, storage_service

router = APIRouter(prefix="/attendance", tags=["attendance"])

# ── Selfie check-in helpers ───────────────────────────────────────────────────
_SELFIE_MAX_FILE_BYTES = 10 * 1024 * 1024
_SELFIE_MAX_FRAMES = 16
_SELFIE_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


def _client_ip(request: Request) -> str | None:
    """Real client IP — first hop of X-Forwarded-For (set by Nginx), else peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _is_from_lan(ip: str | None) -> bool:
    """
    True if `ip` is on the office network.

    If SELFIE_ALLOWED_SUBNETS is configured, membership is checked against those
    CIDRs. Otherwise any private/loopback (RFC1918) address counts as on-LAN,
    which fits the default single-PC LAN install.
    """
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    configured = [c.strip() for c in settings.SELFIE_ALLOWED_SUBNETS.split(",") if c.strip()]
    if configured:
        for cidr in configured:
            try:
                if addr in ipaddress.ip_network(cidr, strict=False):
                    return True
            except ValueError:
                continue
        return False
    return addr.is_private or addr.is_loopback


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors (0.0 on degenerate input)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return dot / (na * nb)


async def _verify_selfie(
    frames: list[tuple[bytes, str, str]],
    challenge: str = "",
) -> dict:
    """POST the burst to the face-service /verify-selfie endpoint; return its JSON.

    `challenge` is the head-turn direction the client prompted ("left"/"right"); the
    face service verifies the head actually turned that way (direction-matched
    liveness), so a generic replayed head-movement video won't reliably pass.
    """
    files = [("frames", (name, data, ctype)) for (data, name, ctype) in frames]
    data = {"challenge": challenge} if challenge else None
    url = f"{settings.FACE_SERVICE_URL}/verify-selfie"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, files=files, data=data)
    except httpx.HTTPError as exc:
        raise UnprocessableError(f"Face service unavailable: {exc}") from exc
    if resp.status_code != 200:
        body = resp.text[:200]
        raise UnprocessableError(f"Face service error {resp.status_code}: {body}")
    try:
        return resp.json()
    except Exception as exc:
        raise UnprocessableError(f"Unexpected face service response: {exc}") from exc


def _can_see_all(user: Employee) -> bool:
    """True for admin / HR / manager — roles that hold employees:read or admin:*."""
    perms: list[str] = getattr(user, "_permissions", [])
    return "admin:*" in perms or "employees:read" in perms


def _event_out(ev) -> AttendanceEventOut:
    return AttendanceEventOut(
        id=ev.id,
        employee_id=ev.employee_id,
        branch_id=ev.branch_id,
        device_id=ev.device_id,
        event_type=ev.event_type,
        source=ev.source,
        raw_timestamp=ev.raw_timestamp,
        corrected_timestamp=ev.corrected_timestamp,
        confidence_score=ev.confidence_score,
        biometric_uid=ev.biometric_uid,
        created_at=ev.created_at,
    )


def _daily_out(d) -> DailyAttendanceOut:
    return DailyAttendanceOut(
        id=d.id,
        employee_id=d.employee_id,
        date=d.date,
        check_in=d.check_in,
        check_out=d.check_out,
        work_minutes=d.work_minutes,
        overtime_minutes=d.overtime_minutes,
        late_minutes=d.late_minutes,
        is_late=d.is_late,
        status=d.status,
        source=d.source,
        notes=d.notes,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


async def _correction_out(daily) -> CorrectionOut:
    import json
    corr: dict = {}
    if daily.notes:
        try:
            corr = json.loads(daily.notes).get("correction", {})
        except Exception:
            pass
    proof_url = None
    if corr.get("proof_path"):
        try:
            proof_url = await storage_service.get_presigned_url(corr["proof_path"], expires_hours=1)
        except Exception:
            proof_url = None
    return CorrectionOut(
        daily_id=daily.id,
        employee_id=daily.employee_id,
        date=daily.date,
        correction_status=corr.get("correction_status", "pending"),
        requested_check_in=(
            datetime.fromisoformat(corr["requested_check_in"])
            if corr.get("requested_check_in") else None
        ),
        requested_check_out=(
            datetime.fromisoformat(corr["requested_check_out"])
            if corr.get("requested_check_out") else None
        ),
        reason=corr.get("reason", ""),
        manager_remarks=corr.get("manager_remarks"),
        hr_remarks=corr.get("hr_remarks"),
        remarks=corr.get("remarks"),
        current_attendance_status=daily.status,
        proof_url=proof_url,
    )


# ── Event ingestion endpoints ─────────────────────────────────────────────────

@router.post("/camera-event", response_model=ApiResponse[DailyAttendanceOut])
async def camera_event(
    body: CameraEventIn,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("attendance:write")),
):
    """Called by the face-recognition microservice after a confident detection."""
    _, daily = await attendance_service.process_event(
        db,
        employee_id=body.employee_id,
        branch_id=body.branch_id,
        event_type=body.event_type,
        source=AttendanceSource.FACE_RECOGNITION,
        raw_timestamp=body.timestamp,
        device_id=body.device_id,
        confidence_score=body.confidence_score,
        proof_storage_path=body.proof_storage_path,
    )
    return ApiResponse.ok(_daily_out(daily))


@router.post("/biometric-event", response_model=ApiResponse[DailyAttendanceOut])
async def biometric_event(body: BiometricEventIn, db: AsyncSession = Depends(get_db)):
    """
    ZKTeco K40 ADMS push endpoint — intentionally unauthenticated.

    ZKTeco devices cannot send JWT headers; security relies on:
    - Device registration check (sn must match a registered device UID)
    - Network isolation (backend not directly public-facing)
    """
    _, daily = await attendance_service.process_biometric_event(
        db,
        sn=body.sn,
        uid=body.uid,
        device_time_str=body.time,
        state_str=body.state,
    )
    return ApiResponse.ok(_daily_out(daily))


@router.post("/manual-event", response_model=ApiResponse[DailyAttendanceOut])
async def manual_event(
    body: ManualEventIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:write")),
):
    """HR direct manual event entry."""
    event, daily = await attendance_service.process_event(
        db,
        employee_id=body.employee_id,
        branch_id=current_user.branch_id,
        event_type=body.event_type,
        source=AttendanceSource.MANUAL,
        raw_timestamp=body.timestamp,
    )
    await record_audit(
        db, table_name="attendance_events", record_id=event.id,
        action=AuditAction.CREATE, performed_by_id=current_user.id,
        after={"employee_id": str(body.employee_id),
               "event_type": body.event_type.value,
               "source": "manual", "timestamp": str(body.timestamp)},
    )
    return ApiResponse.ok(_daily_out(daily))


@router.get("/selfie-config", response_model=ApiResponse[dict])
async def selfie_config(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """Whether self-service selfie check-in is enabled, and today's status for the caller."""
    cfg = await attendance_service.get_selfie_config(db)
    today = attendance_service._to_ist_date(datetime.now(timezone.utc))
    daily = await attendance_service.get_daily(db, current_user.id, today)
    enrolled = bool(
        [e for e in await face_service.get_embeddings_for_employee(db, current_user.id)
         if e.is_active]
    )
    return ApiResponse.ok({
        "enabled": cfg["enabled"],
        "enrolled": enrolled,
        "checked_in": bool(daily and daily.check_in),
        "checked_out": bool(daily and daily.check_out),
        "check_in": daily.check_in.isoformat() if daily and daily.check_in else None,
        "check_out": daily.check_out.isoformat() if daily and daily.check_out else None,
    })


@router.post("/selfie-checkin", response_model=ApiResponse[DailyAttendanceOut])
async def selfie_checkin(
    request: Request,
    event_type: str = Form("ENTRY"),
    challenge: str = Form(""),
    frames: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """
    Self-service selfie check-in (LAN-gated, 1:1 face match + liveness).

    The employee submits a short burst of selfie frames captured during a
    head-movement challenge. The face-service confirms liveness and returns an
    embedding; the backend matches it 1:1 against the caller's own enrolled face,
    flags whether the request came from the office LAN, and records the event.
    """
    et = event_type.strip().upper()
    if et not in ("ENTRY", "EXIT"):
        raise UnprocessableError("event_type must be ENTRY or EXIT")
    evt = EventType.ENTRY if et == "ENTRY" else EventType.EXIT

    cfg = await attendance_service.get_selfie_config(db)
    if not cfg["enabled"]:
        raise UnprocessableError("Selfie check-in is disabled by the administrator.")

    if not frames:
        raise UnprocessableError("No selfie frames provided")
    payload_frames: list[tuple[bytes, str, str]] = []
    for f in frames[:_SELFIE_MAX_FRAMES]:
        ctype = f.content_type or "image/jpeg"
        if ctype not in _SELFIE_ALLOWED_MIME:
            raise UnprocessableError(f"Unsupported image type '{ctype}'.")
        data = await f.read()
        if len(data) > _SELFIE_MAX_FILE_BYTES:
            raise UnprocessableError("A selfie frame exceeds the 10 MB limit.")
        if data:
            payload_frames.append((data, f.filename or "frame.jpg", ctype))
    if not payload_frames:
        raise UnprocessableError("All selfie frames were empty.")

    # Must be enrolled (1:1 needs a reference embedding).
    embeddings = await face_service.get_embeddings_for_employee(db, current_user.id)
    active = [e for e in embeddings if e.is_active and e.embedding]
    if not active:
        raise UnprocessableError(
            "You are not enrolled for face check-in yet. "
            "Ask HR or an administrator to enroll your face first."
        )

    ip = _client_ip(request)
    from_lan = _is_from_lan(ip)

    result = await _verify_selfie(payload_frames, challenge=challenge.strip().lower())
    if not result.get("ok"):
        raise UnprocessableError(
            result.get("reason")
            or "Could not read a face from the selfie. Try again in good lighting."
        )
    liveness = result.get("liveness") or {}
    if not liveness.get("active_passed"):
        raise UnprocessableError(
            "Liveness check failed — follow the on-screen prompt and move your head as asked."
        )
    if not liveness.get("passive_passed"):
        raise UnprocessableError(
            "Liveness check failed — a photo or screen was detected. Use your live face."
        )
    query_emb = result.get("embedding")
    if not query_emb:
        raise UnprocessableError("Could not extract a face embedding from the selfie.")

    best_sim = 0.0
    for e in active:
        sim = _cosine(query_emb, e.embedding)
        if sim > best_sim:
            best_sim = sim
    threshold = cfg["threshold"]
    if best_sim < threshold:
        raise UnprocessableError(
            f"Face did not match your profile (similarity {best_sim:.2f}, "
            f"need {threshold:.2f}). Face the camera in good light and try again."
        )

    # Store the first frame as the proof image (best-effort).
    now_utc = datetime.now(timezone.utc)
    ts_tag = now_utc.strftime("%Y%m%d_%H%M%S")
    object_key = f"selfie/{current_user.id}/{ts_tag}_{et.lower()}.jpg"
    proof_path: str | None = None
    try:
        await storage_service.upload_proof_frame(object_key, payload_frames[0][0])
        proof_path = object_key
    except Exception:
        proof_path = None

    _, daily = await attendance_service.process_selfie_event(
        db,
        employee_id=current_user.id,
        branch_id=current_user.branch_id,
        event_type=evt,
        raw_timestamp=now_utc,
        confidence_score=best_sim,
        proof_storage_path=proof_path,
        from_lan=from_lan,
        ip_address=ip,
    )
    return ApiResponse.ok(_daily_out(daily))


# ── Daily attendance queries ──────────────────────────────────────────────────

@router.get("/daily", response_model=ApiResponse[list[DailyAttendanceOut]])
async def list_daily(
    employee_id: uuid.UUID | None = Query(default=None),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    status: AttendanceStatus | None = Query(default=None),
    # Higher cap than other lists: a whole-company date range (≤20 employees × a
    # month) is a legitimate single fetch here, and the frontend renders them all.
    per_page: int = Query(default=30, ge=1, le=1000),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:read")),
):
    # Scope by role: HR/Admin see all; a manager sees their department; an employee
    # sees only themselves. A manager/employee querying a specific employee_id may only
    # do so within their scope.
    scope = await visible_employee_ids(db, current_user)
    employee_ids = None
    if scope is not None:
        if employee_id is not None:
            if employee_id not in scope:
                raise ForbiddenError(
                    "You can only view attendance for employees in your department."
                )
        else:
            employee_ids = scope
    records, pagination = await attendance_service.list_daily(
        db,
        employee_id=employee_id,
        employee_ids=employee_ids,
        from_date=from_date,
        to_date=to_date,
        status=status,
        per_page=per_page,
        cursor=cursor,
    )
    return ApiResponse.ok([_daily_out(r) for r in records], pagination)


@router.get(
    "/daily/{employee_id}/{att_date}",
    response_model=ApiResponse[DailyAttendanceOut],
)
async def get_daily(
    employee_id: uuid.UUID,
    att_date: date,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:read")),
):
    if not _can_see_all(current_user) and employee_id != current_user.id:
        raise ForbiddenError("You can only view your own attendance records")
    daily = await attendance_service.get_daily(db, employee_id, att_date)
    if not daily:
        raise NotFoundError(f"No attendance record for {employee_id} on {att_date}")
    return ApiResponse.ok(_daily_out(daily))


@router.patch(
    "/daily/{employee_id}/{att_date}",
    response_model=ApiResponse[DailyAttendanceOut],
)
async def override_daily(
    employee_id: uuid.UUID,
    att_date: date,
    body: DailyOverrideIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:write")),
):
    """HR manual override — adjusts check_in/check_out and triggers recalculation."""
    daily = await attendance_service.manual_override(
        db,
        employee_id=employee_id,
        ist_date=att_date,
        check_in=body.check_in,
        check_out=body.check_out,
        status_override=body.status,
        notes=body.notes,
        actor_id=current_user.id,
    )
    return ApiResponse.ok(_daily_out(daily))


# ── Proof images ──────────────────────────────────────────────────────────────

@router.get(
    "/daily/{employee_id}/{att_date}/proof",
    response_model=ApiResponse[list[ProofOut]],
)
async def get_proofs(
    employee_id: uuid.UUID,
    att_date: date,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("attendance:read")),
):
    """Return presigned MinIO URLs (1-hour expiry) for all proof frames for the day."""
    proofs = await attendance_service.get_proofs_for_day(db, employee_id, att_date)
    items: list[ProofOut] = []
    for p in proofs:
        try:
            url = await storage_service.get_presigned_url(p.storage_path, expires_hours=1)
        except Exception:
            url = p.storage_path  # fallback: return raw object key if MinIO unavailable
        items.append(
            ProofOut(
                id=p.id,
                event_id=p.attendance_event_id,
                proof_type=p.proof_type,
                url=url,
                captured_at=p.captured_at,
            )
        )
    return ApiResponse.ok(items)


# ── Raw event list ────────────────────────────────────────────────────────────

@router.get("/events", response_model=ApiResponse[list[AttendanceEventOut]])
async def list_events(
    employee_id: uuid.UUID | None = Query(default=None),
    from_dt: datetime | None = Query(default=None),
    to_dt: datetime | None = Query(default=None),
    per_page: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:read")),
):
    if not _can_see_all(current_user):
        employee_id = current_user.id
    events, pagination = await attendance_service.list_events(
        db,
        employee_id=employee_id,
        from_dt=from_dt,
        to_dt=to_dt,
        per_page=per_page,
        cursor=cursor,
    )
    return ApiResponse.ok([_event_out(e) for e in events], pagination)


# ── Corrections workflow ──────────────────────────────────────────────────────

@router.get("/corrections", response_model=ApiResponse[list[CorrectionOut]])
async def list_corrections(
    employee_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:read")),
):
    """Return correction requests. HR/Admin see all; a manager sees their department;
    an employee sees only their own."""
    scope = await visible_employee_ids(db, current_user)
    records = await attendance_service.list_corrections(
        db,
        employee_id=(employee_id if scope is None else None),
        employee_ids=scope,
    )
    return ApiResponse.ok([await _correction_out(r) for r in records])


@router.post("/corrections", response_model=ApiResponse[CorrectionOut], status_code=201)
async def submit_correction(
    body: CorrectionRequestIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:read")),
):
    """
    Employee submits a correction request for their own attendance record.
    Employees can only correct their own records; HR/managers can submit for any employee.
    """
    daily = await attendance_service.submit_correction(
        db,
        employee_id=current_user.id,  # employees can only correct their own record
        ist_date=body.date,
        requested_check_in=body.requested_check_in,
        requested_check_out=body.requested_check_out,
        reason=body.reason,
    )
    return ApiResponse.ok(await _correction_out(daily))


@router.post(
    "/corrections/{daily_id}/proof",
    response_model=ApiResponse[CorrectionOut],
    status_code=201,
)
async def upload_correction_proof(
    daily_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:read")),
):
    """
    Attach an optional supporting proof (image or PDF, max 10 MB) to the caller's
    own pending correction request. Stored privately in MinIO; surfaced as a
    presigned URL in the correction's `proof_url`.
    """
    import os as _os
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise UnprocessableError("File too large — maximum size is 10 MB")

    slot_id = uuid.uuid4()
    content_type = file.content_type or "application/octet-stream"
    raw_name = (file.filename or "proof").replace("\x00", "")
    filename = _os.path.basename(raw_name) or "proof"

    object_path = await storage_service.upload_correction_proof(
        daily_id=daily_id,
        slot_id=slot_id,
        filename=filename,
        data=data,
        content_type=content_type,
    )
    daily = await attendance_service.attach_correction_proof(
        db,
        daily_id=daily_id,
        employee_id=current_user.id,
        proof_path=object_path,
    )
    return ApiResponse.ok(await _correction_out(daily))


@router.delete("/corrections/{daily_id}", response_model=ApiResponse[DailyAttendanceOut])
async def cancel_correction(
    daily_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:read")),
):
    """
    Withdraw a not-yet-approved correction request; the day reverts to its computed
    status. Employees may cancel their own; HR/Admin may cancel any pending correction.
    """
    daily = await attendance_service.cancel_correction(
        db, daily_id=daily_id, actor_id=current_user.id, is_privileged=is_hr_tier(current_user)
    )
    return ApiResponse.ok(_daily_out(daily))


@router.patch(
    "/corrections/{daily_id}/approve",
    response_model=ApiResponse[DailyAttendanceOut],
)
async def approve_correction(
    daily_id: uuid.UUID,
    body: CorrectionActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:write")),
):
    daily = await attendance_service.action_correction(
        db,
        daily_id=daily_id,
        actor_id=current_user.id,
        approve=True,
        remarks=body.remarks,
    )
    return ApiResponse.ok(_daily_out(daily))


@router.patch(
    "/corrections/{daily_id}/reject",
    response_model=ApiResponse[DailyAttendanceOut],
)
async def reject_correction(
    daily_id: uuid.UUID,
    body: CorrectionActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:write")),
):
    daily = await attendance_service.action_correction(
        db,
        daily_id=daily_id,
        actor_id=current_user.id,
        approve=False,
        remarks=body.remarks,
    )
    return ApiResponse.ok(_daily_out(daily))


@router.patch(
    "/corrections/{daily_id}/manager-approve",
    response_model=ApiResponse[CorrectionOut],
)
async def manager_approve_correction(
    daily_id: uuid.UUID,
    body: CorrectionActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:write")),
):
    """
    Manager first-level approval.
    Transitions correction_status: pending → pending_hr.
    The requested times are NOT applied yet — HR must approve next.
    """
    # A manager may only approve corrections for their own department's employees.
    from sqlalchemy import select as _select
    from app.models.daily_attendance import DailyAttendance as _Daily
    owner = (
        await db.execute(_select(_Daily.employee_id).where(_Daily.id == daily_id))
    ).scalar_one_or_none()
    if owner is not None:
        await assert_can_act_on(db, current_user, owner)
    daily = await attendance_service.manager_approve_correction(
        db,
        daily_id=daily_id,
        manager_id=current_user.id,
        remarks=body.remarks,
    )
    return ApiResponse.ok(await _correction_out(daily))


@router.patch(
    "/corrections/{daily_id}/hr-approve",
    response_model=ApiResponse[DailyAttendanceOut],
)
async def hr_approve_correction(
    daily_id: uuid.UUID,
    body: CorrectionActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:write")),
):
    """
    HR/Admin final approval (may also finalize a correction still at the manager stage).
    Applies the requested check_in/check_out, recalculates attendance status,
    and marks correction_status: approved.
    """
    require_hr_tier_final_approval(current_user)
    daily = await attendance_service.hr_approve_correction(
        db,
        daily_id=daily_id,
        hr_id=current_user.id,
        remarks=body.remarks,
    )
    return ApiResponse.ok(_daily_out(daily))
