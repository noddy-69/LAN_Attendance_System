"""
tests/test_e2e_happy_path.py
============================
End-to-end happy path covering the complete user journey:

  1.  Employee onboarding  — create devices + employees via HTTP API
  2.  Face enrollment      — seed 512-dim embedding in DB, verify via API
                             (InsightFace extraction tested separately in A8)
  3.  Attendance           — POST camera-event (ENTRY + EXIT) → PRESENT, on time
  4.  Leave workflow       — employee applies CL → manager approves → HR approves
  5.  Balance & status     — used_days decremented; daily_attendance = ON_LEAVE
  6.  Payroll deduction    — 12 late days, ₹30k salary → ₹500 (0.5 day @ ₹1,000)
  7.  Notifications        — LEAVE_APPLIED + LEAVE_APPROVED + PAYROLL_DEDUCTION
                             delivered (on-time check-in emits none); read-all clears
                             unread count

Run inside the backend container:
    docker compose exec backend pytest tests/test_e2e_happy_path.py -v --tb=short

Tests run in file-definition order (pytest default for top-level functions).
Each test stores new IDs in the shared `ctx` dict for downstream tests.

Environment:
    E2E_BASE_URL  — backend API base URL (default: http://localhost:8000)
    DATABASE_URL  — injected automatically by Docker Compose
"""

import os
import time
import uuid
from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models.attendance_event import AttendanceSource
from app.models.daily_attendance import AttendanceStatus, DailyAttendance
from app.models.face_embedding import FaceEmbedding
from app.models.leave import LeaveStatus
from app.models.notification import Notification, NotificationEvent, NotificationStatus

# ── Configuration ─────────────────────────────────────────────────────────────

_BASE    = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
_A_EMAIL = "admin@test.com"
_A_PASS  = "Admin@1234"
_E_PASS  = "TestPass@1234"

# Attendance test: 2026-06-17 (Wednesday, not a seeded national holiday)
_ATT_DATE  = date(2026, 6, 17)
_ENTRY_UTC = datetime(2026, 6, 17, 3, 30, 0, tzinfo=timezone.utc)   # 09:00 IST
_EXIT_UTC  = datetime(2026, 6, 17, 12, 30, 0, tzinfo=timezone.utc)  # 18:00 IST

# Leave test: 2026-06-24..25 (Wednesday + Thursday, not seeded holidays)
_LEAVE_START = date(2026, 6, 24)
_LEAVE_END   = date(2026, 6, 25)

# Payroll test (percentage-of-a-day model). 12 late days in July 2026.
# Seeded policy: every 3 lates = 1 unit, each unit = 50% of a day, 1.5 grace days,
# a day's salary = monthly / 30. Salary ₹30,000/mo → ₹1,000/day.
#   units = 12 // 3 = 4 ; gross = 4 × 0.5 = 2.0 days ; net = 2.0 − 1.5 = 0.5 day
#   deduction = 0.5 × ₹1,000 = ₹500
_LATE_MONTH = 7
_LATE_YEAR  = 2026
_LATE_COUNT = 12
_SALARY_P   = 3_000_000       # ₹30,000 monthly in paise
_UNITS      = 4
_NET_DAYS   = 0.5
_DAILY_P    = 100_000         # ₹1,000/day in paise
_TOTAL_P    = 50_000          # ₹500 in paise

# Unique suffix prevents collisions when re-running against the same live DB
_SFX = uuid.uuid4().hex[:8].upper()


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _req(method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
    """Single-shot HTTP request to the backend API."""
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(base_url=_BASE, timeout=30) as c:
        return c.request(method, f"/api/v1{path}", headers=headers, **kw)


def _ok(resp: httpx.Response, label: str = ""):
    """Assert HTTP 2xx + success=true; return response data payload."""
    tag = f"[{label}] " if label else ""
    assert resp.status_code < 300, (
        f"{tag}HTTP {resp.status_code}: {resp.text[:500]}"
    )
    body = resp.json()
    assert body.get("success") is True, f"{tag}success=false: {body}"
    return body["data"]


def _poll(fn, *, max_wait: int = 10, interval: float = 1.0):
    """
    Retry fn() every `interval` seconds for up to `max_wait` seconds.
    Returns the first truthy result, or the last result on timeout.
    Used to tolerate Celery's asynchronous notification delivery.
    """
    deadline = time.monotonic() + max_wait
    result = None
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    return result


# ── DB session that commits (for seeding data that must persist) ──────────────

@pytest.fixture(scope="module")
def edb(db_engine):
    """
    Synchronous, committing SQLAlchemy session for E2E data seeding.
    Unlike the conftest db_session, this fixture COMMITS and never rolls back,
    so seeded rows are visible to the running FastAPI/Celery services.
    """
    conn = db_engine.connect()
    sess = sessionmaker(bind=conn, expire_on_commit=False)()
    yield sess
    sess.close()
    conn.close()


# ── One-time module setup — runs before the first test ───────────────────────

@pytest.fixture(scope="module")
def ctx(edb):
    """
    Authenticate as admin, create all test entities, seed face embedding and
    late-attendance rows. Yields the shared context dict; individual tests
    read from it and may add new keys (e.g. leave_id, ded_id).
    """
    c: dict = {}

    # ── 1. Admin login ────────────────────────────────────────────────────────
    d = _ok(
        _req("POST", "/auth/login",
             json={"email": _A_EMAIL, "password": _A_PASS}),
        "admin_login",
    )
    c["tok"] = d["access_token"]

    # ── 2. Resolve seeded branch ──────────────────────────────────────────────
    branches = _ok(_req("GET", "/branches", token=c["tok"]), "branches")
    assert branches, "No branches in DB — run seed-db.sh first"
    c["branch_id"] = branches[0]["id"]

    # ── 3. Resolve role IDs ───────────────────────────────────────────────────
    roles = _ok(_req("GET", "/roles", token=c["tok"]), "roles")
    role_map = {r["name"]: r["id"] for r in roles}
    c["emp_role_id"] = role_map["employee"]
    c["mgr_role_id"] = role_map["manager"]

    # ── 4. Resolve Casual Leave type ─────────────────────────────────────────
    ltypes = _ok(_req("GET", "/leave/types", token=c["tok"]), "leave_types")
    cl = next((lt for lt in ltypes if lt["code"] == "CL"), None)
    assert cl, "CL leave type not found — run seed-db.sh first"
    c["cl_type_id"] = cl["id"]

    # ── 5. Create test camera device ─────────────────────────────────────────
    d = _ok(
        _req("POST", "/devices", token=c["tok"], json={
            "name":            f"E2E Camera {_SFX}",
            "device_type":     "camera",
            "branch_id":       c["branch_id"],
            "is_entry_camera": True,
            "rtsp_url":        "rtsp://admin:test@192.168.99.1:554/stream",
        }),
        "create_device",
    )
    c["device_id"] = d["id"]

    # ── 6. Create manager employee (M1) ───────────────────────────────────────
    d = _ok(
        _req("POST", "/employees", token=c["tok"], json={
            "employee_code":   f"E2EM{_SFX}",
            "first_name":      "E2EManager",
            "last_name":       _SFX,
            "email":           f"e2em.{_SFX.lower()}@test.com",
            "password":        _E_PASS,
            "role_id":         c["mgr_role_id"],
            "branch_id":       c["branch_id"],
            "date_of_joining": "2025-01-01",
        }),
        "create_manager",
    )
    c["m1_id"] = d["id"]

    # ── 7. Create test employee (E1) ──────────────────────────────────────────
    d = _ok(
        _req("POST", "/employees", token=c["tok"], json={
            "employee_code":   f"E2EE{_SFX}",
            "first_name":      "E2EEmployee",
            "last_name":       _SFX,
            "email":           f"e2ee.{_SFX.lower()}@test.com",
            "password":        _E_PASS,
            "role_id":         c["emp_role_id"],
            "branch_id":       c["branch_id"],
            "manager_id":      c["m1_id"],
            "date_of_joining": "2025-01-01",
            "monthly_salary_paise": _SALARY_P,
        }),
        "create_employee",
    )
    c["e1_id"] = d["id"]

    # ── 8. Login as E1 ────────────────────────────────────────────────────────
    d = _ok(
        _req("POST", "/auth/login", json={
            "email":    f"e2ee.{_SFX.lower()}@test.com",
            "password": _E_PASS,
        }),
        "emp_login",
    )
    c["e1_tok"] = d["access_token"]

    # ── 9. Grant E1 a CL balance of 12 days for 2026 ─────────────────────────
    _ok(
        _req("POST", "/leave/balance/adjust", token=c["tok"], json={
            "employee_id":          c["e1_id"],
            "leave_type_id":        c["cl_type_id"],
            "year":                 2026,
            "allocated_days":       12.0,
            "carried_forward_days": 0.0,
        }),
        "adjust_balance",
    )

    # ── 10. Seed face embedding for E1 (direct DB) ────────────────────────────
    # InsightFace extraction is tested in A8; here we seed a 512-dim placeholder
    # so the attendance tests (camera-event) reference an enrolled employee.
    emb = FaceEmbedding(
        employee_id=uuid.UUID(c["e1_id"]),
        embedding=[0.0] * 512,
        model_version="buffalo_sc",
        is_active=True,
    )
    edb.add(emb)
    edb.commit()
    c["emb_id"] = str(emb.id)

    # ── 11. Seed 7 late daily-attendance rows in July 2026 (payroll test) ─────
    # Use BIOMETRIC source so they don't interact with the face-rec attendance test.
    for day in range(1, _LATE_COUNT + 1):
        edb.add(DailyAttendance(
            employee_id=uuid.UUID(c["e1_id"]),
            date=date(_LATE_YEAR, _LATE_MONTH, day),
            status=AttendanceStatus.LATE,
            source=AttendanceSource.BIOMETRIC,
            is_late=True,
            late_minutes=15,
        ))
    edb.commit()

    yield c
    # No teardown — test entities stay in DB (identified by _SFX suffix).
    # Acceptable for test/dev environments; run `seed-db.sh` to reset fully.


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 — Face enrollment
# ═══════════════════════════════════════════════════════════════════════════════

def test_01_face_embedding_in_db(ctx, edb):
    """Active 512-dim embedding exists in face_embeddings for E1."""
    rows = edb.execute(
        select(FaceEmbedding).where(
            FaceEmbedding.employee_id == uuid.UUID(ctx["e1_id"]),
            FaceEmbedding.is_active.is_(True),
        )
    ).scalars().all()
    assert len(rows) >= 1, "No active face embedding found for E1"
    assert len(rows[0].embedding) == 512, (
        f"Embedding must be 512-dimensional, got {len(rows[0].embedding)}"
    )


def test_02_enrollment_status_api(ctx):
    """GET /face/employees/{id}/enrollment-status reports is_enrolled=True."""
    d = _ok(
        _req(
            "GET",
            f"/face/employees/{ctx['e1_id']}/enrollment-status",
            token=ctx["tok"],
        ),
        "enrollment_status",
    )
    assert d["is_enrolled"] is True, "Employee should be enrolled after embedding seed"
    assert d["active_embedding_count"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Attendance via face-recognition camera events
# ═══════════════════════════════════════════════════════════════════════════════

def test_03_camera_entry_event(ctx):
    """
    Face-rec service posts ENTRY at 09:00 IST.
    Engine records check_in; employee is on time (09:00 < late threshold).
    """
    d = _ok(
        _req("POST", "/attendance/camera-event", token=ctx["tok"], json={
            "employee_id":      ctx["e1_id"],
            "device_id":        ctx["device_id"],
            "branch_id":        ctx["branch_id"],
            "event_type":       "ENTRY",
            "timestamp":        _ENTRY_UTC.isoformat(),
            "confidence_score": 0.97,
        }),
        "camera_entry",
    )
    assert d["check_in"] is not None, "check_in must be set after ENTRY event"
    assert d["is_late"] is False, (
        f"09:00 IST should be on time (before late threshold); got: {d}"
    )
    assert d["source"] == AttendanceSource.FACE_RECOGNITION.value


def test_04_camera_exit_event(ctx):
    """
    Face-rec service posts EXIT at 18:00 IST.
    work_minutes = 18:00 − 09:00 = 540 min; status = PRESENT.
    """
    d = _ok(
        _req("POST", "/attendance/camera-event", token=ctx["tok"], json={
            "employee_id":      ctx["e1_id"],
            "device_id":        ctx["device_id"],
            "branch_id":        ctx["branch_id"],
            "event_type":       "EXIT",
            "timestamp":        _EXIT_UTC.isoformat(),
            "confidence_score": 0.96,
        }),
        "camera_exit",
    )
    assert d["check_out"] is not None, "check_out must be set after EXIT event"
    assert d["work_minutes"] == 540, (
        f"Expected 540 work-minutes (9 hours), got {d['work_minutes']}"
    )
    assert d["status"] == AttendanceStatus.PRESENT.value


def test_05_daily_attendance_record(ctx):
    """
    GET /attendance/daily/{e1}/{date} returns PRESENT, source=face_recognition,
    correct check_in and check_out timestamps.
    """
    d = _ok(
        _req(
            "GET",
            f"/attendance/daily/{ctx['e1_id']}/{_ATT_DATE.isoformat()}",
            token=ctx["tok"],
        ),
        "get_daily",
    )
    assert d["status"] == AttendanceStatus.PRESENT.value
    assert d["is_late"] is False
    assert d["source"] == AttendanceSource.FACE_RECOGNITION.value
    assert d["check_in"] is not None
    assert d["check_out"] is not None
    assert d["work_minutes"] == 540


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Leave request → manager approval → HR approval
# ═══════════════════════════════════════════════════════════════════════════════

def test_06_employee_applies_leave(ctx):
    """E1 applies 2-day CL for 2026-06-24..25; status = pending_manager."""
    d = _ok(
        _req("POST", "/leave/apply", token=ctx["e1_tok"], json={
            "leave_type_id": ctx["cl_type_id"],
            "start_date":    _LEAVE_START.isoformat(),
            "end_date":      _LEAVE_END.isoformat(),
            "reason":        f"E2E test leave {_SFX}",
        }),
        "leave_apply",
    )
    assert d["status"] == LeaveStatus.PENDING_MANAGER.value
    assert float(d["days_requested"]) == 2.0
    assert d["employee_id"] == ctx["e1_id"]
    ctx["leave_id"] = d["id"]


def test_07_manager_approves_leave(ctx):
    """Manager (admin) approves leave request; status moves to pending_hr."""
    d = _ok(
        _req(
            "POST",
            f"/leave/requests/{ctx['leave_id']}/manager-approve",
            token=ctx["tok"],
            json={"remarks": "E2E manager approval"},
        ),
        "mgr_approve",
    )
    assert d["status"] == LeaveStatus.PENDING_HR.value
    assert d["manager_remarks"] == "E2E manager approval"


def test_08_hr_approves_leave(ctx):
    """HR (admin) final-approves leave; status = approved."""
    d = _ok(
        _req(
            "POST",
            f"/leave/requests/{ctx['leave_id']}/hr-approve",
            token=ctx["tok"],
            json={"remarks": "E2E HR approval"},
        ),
        "hr_approve",
    )
    assert d["status"] == LeaveStatus.APPROVED.value
    assert d["hr_remarks"] == "E2E HR approval"


def test_09_leave_balance_decremented(ctx):
    """After approval, CL used_days = 2.0 and available_days = 10.0."""
    balances = _ok(
        _req(
            "GET",
            f"/leave/balance/{ctx['e1_id']}",
            token=ctx["tok"],
            params={"year": 2026},
        ),
        "leave_balance",
    )
    cl = next((b for b in balances if b["leave_type_code"] == "CL"), None)
    assert cl is not None, "CL balance not found for E1"
    assert float(cl["used_days"])      == 2.0,  f"used_days: {cl['used_days']}"
    assert float(cl["allocated_days"]) == 12.0, f"allocated: {cl['allocated_days']}"
    assert float(cl["available_days"]) == 10.0, f"available: {cl['available_days']}"


def test_10_leave_dates_on_leave_status(ctx):
    """Both approved leave days appear as ON_LEAVE in daily_attendance."""
    for day in [_LEAVE_START, _LEAVE_END]:
        d = _ok(
            _req(
                "GET",
                f"/attendance/daily/{ctx['e1_id']}/{day.isoformat()}",
                token=ctx["tok"],
            ),
            f"daily_{day}",
        )
        assert d["status"] == AttendanceStatus.ON_LEAVE.value, (
            f"{day}: expected ON_LEAVE, got {d['status']}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4 — Payroll deduction
# ═══════════════════════════════════════════════════════════════════════════════

def test_11_payroll_deduction_math(ctx):
    """
    Percentage-of-a-day model: 12 lates → 4 units → 2.0 days gross − 1.5 grace
    = 0.5 day net × ₹1,000/day = ₹500 (50 000 paise).
    total_deduction_paise must be INTEGER (not float).
    """
    d = _ok(
        _req("POST", "/payroll/deductions/calculate", token=ctx["tok"], json={
            "employee_id": ctx["e1_id"],
            "month":       _LATE_MONTH,
            "year":        _LATE_YEAR,
        }),
        "calc_deduction",
    )
    assert d["late_count"]    == _LATE_COUNT, (
        f"late_count: expected {_LATE_COUNT}, got {d['late_count']}"
    )
    assert d["penalty_units"] == _UNITS, (
        f"penalty_units: expected {_UNITS}, got {d['penalty_units']}"
    )
    assert d["net_penalty_days"] == _NET_DAYS, (
        f"net_penalty_days: expected {_NET_DAYS}, got {d['net_penalty_days']}"
    )
    assert d["daily_salary_paise"] == _DAILY_P, (
        f"daily_salary: expected {_DAILY_P}, got {d['daily_salary_paise']}"
    )
    assert d["total_deduction_paise"] == _TOTAL_P, (
        f"total paise: expected {_TOTAL_P} (₹{_TOTAL_P // 100}), "
        f"got {d['total_deduction_paise']}"
    )
    assert isinstance(d["total_deduction_paise"], int), (
        "total_deduction_paise must be INTEGER paise, not float"
    )
    ctx["ded_id"] = d["id"]


def test_12_payroll_csv_report(ctx):
    """
    Monthly payroll CSV for July 2026 contains E1's employee code
    and the ₹500 deduction amount.
    """
    resp = _req(
        "GET",
        "/payroll/deductions/report",
        token=ctx["tok"],
        params={
            "month":  f"{_LATE_YEAR}-{_LATE_MONTH:02d}",
            "format": "csv",
        },
    )
    assert resp.status_code == 200, f"Report HTTP {resp.status_code}: {resp.text[:200]}"
    assert "text/csv" in resp.headers.get("content-type", ""), (
        f"Expected CSV content-type, got: {resp.headers.get('content-type')}"
    )
    csv_text = resp.text
    emp_code = f"E2EE{_SFX}"
    assert emp_code in csv_text, (
        f"Employee code {emp_code!r} not in payroll report:\n{csv_text[:400]}"
    )
    # Deduction column value: ₹500 → 500.0 (rupees, one decimal per spec)
    assert "500.0" in csv_text, (
        f"₹500 deduction (500.0) not found in report:\n{csv_text[:400]}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5 — Notification delivery
# ═══════════════════════════════════════════════════════════════════════════════

def test_13_all_expected_notifications_delivered(ctx):
    """
    E1 receives at least three distinct notification types:
      LEAVE_APPLIED      (from apply in test_06)
      LEAVE_APPROVED     (from hr-approve in test_08)
      PAYROLL_DEDUCTION  (from calculate in test_11)
    (The on-time ENTRY in test_03 intentionally produces no notification.)

    Notifications are queued via Celery; poll for up to 10 s to tolerate
    any async delivery lag.
    """
    # A normal on-time check-in deliberately emits NO notification (that would email
    # every employee every working day). Push notifications are exception-only:
    # LATE_ARRIVAL, ABSENT_ALERT (nightly), plus the leave/payroll workflow events.
    required = {
        NotificationEvent.LEAVE_APPLIED.value,
        NotificationEvent.LEAVE_APPROVED.value,
        NotificationEvent.PAYROLL_DEDUCTION.value,
    }

    def _check():
        data = _ok(
            _req("GET", "/notifications", token=ctx["e1_tok"],
                 params={"per_page": 100}),
            "notifications",
        )
        found = {n["event_type"] for n in data}
        return found if required.issubset(found) else None

    found = _poll(_check, max_wait=10, interval=1.0)
    assert found is not None and required.issubset(found), (
        f"Missing notification types.\n"
        f"  Required : {sorted(required)}\n"
        f"  Received : {sorted(found or set())}"
    )


def test_14_mark_all_notifications_read(ctx):
    """PATCH /notifications/read-all marks all PENDING as SENT; returns updated >= 1."""
    d = _ok(
        _req("PATCH", "/notifications/read-all", token=ctx["e1_tok"]),
        "read_all",
    )
    updated = d.get("updated", 0)
    assert updated >= 1, (
        f"Expected at least 1 notification marked read, got updated={updated}"
    )


def test_15_unread_count_zero_after_read_all(ctx):
    """
    Verify unread_count = 0 after marking all notifications read.
    Calls read-all a second time to drain any notifications Celery may have
    delivered in the window between test_14's read-all and this check.
    """
    # Second read-all catches late-arriving Celery notifications
    _req("PATCH", "/notifications/read-all", token=ctx["e1_tok"])

    d = _ok(
        _req("GET", "/notifications/unread-count", token=ctx["e1_tok"]),
        "unread_count",
    )
    assert d.get("unread_count") == 0, (
        f"Expected unread_count=0 after read-all, got: {d}"
    )
