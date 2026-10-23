"""
Integration test — calculate_monthly_deductions math verification.

Scenario (percentage-of-a-day model)
------------------------------------
  late_days_per_unit       = 3
  penalty_percent_per_unit = 50     (each unit = half a day)
  grace_days               = 1.5
  salary_days_per_month    = 30
  monthly_salary           = ₹30,000 (3,000,000 paise) → ₹1,000/day
  actual late days         = 12
    units    = 12 // 3 = 4
    gross    = 4 × 0.5 = 2.0 days
    net      = max(0, 2.0 − 1.5) = 0.5 day
    deduction = 0.5 × ₹1,000 = ₹500 (50,000 paise)

All data is inserted within a transaction that is rolled back after the test,
so the real database is not polluted. Celery is mocked so no Redis is required.
"""

import json
import uuid
from datetime import date, time
from unittest.mock import patch

from app.models.attendance_event import AttendanceSource
from app.models.branch import Branch
from app.models.daily_attendance import AttendanceStatus, DailyAttendance
from app.models.employee import Employee
from app.models.payroll import SalaryDeduction
from app.models.role import Role
from app.tasks.payroll import calculate_monthly_deductions

# ── Fixed test parameters ──────────────────────────────────────────────────────
TEST_YEAR = 2026
TEST_MONTH = 5          # May — a past, complete month
LATE_DAYS = 12
SALARY_PAISE = 3_000_000   # ₹30,000/month

LATE_DAYS_PER_UNIT = 3
PENALTY_PERCENT = 50
GRACE_DAYS = 1.5
SALARY_DAYS = 30

EXPECTED_UNITS = LATE_DAYS // LATE_DAYS_PER_UNIT             # 4
EXPECTED_NET_X100 = 50                                       # 0.5 day
EXPECTED_DAILY = SALARY_PAISE // SALARY_DAYS                 # 100000
EXPECTED_TOTAL = EXPECTED_DAILY * EXPECTED_NET_X100 // 100   # 50000


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_role(session) -> Role:
    role = Role(name=f"test-role-{uuid.uuid4().hex[:8]}")
    session.add(role)
    session.flush()
    return role


def _make_branch(session) -> Branch:
    branch = Branch(
        name=f"Test Branch {uuid.uuid4().hex[:8]}",
        city="Mumbai",
        state="Maharashtra",
        office_start_time=time(9, 0),
        office_end_time=time(18, 0),
        grace_period_minutes=15,
    )
    session.add(branch)
    session.flush()
    return branch


def _make_employee(session, role: Role, branch: Branch, salary_paise: int = SALARY_PAISE) -> Employee:
    emp = Employee(
        employee_code=f"TST{uuid.uuid4().hex[:6].upper()}",
        first_name="Test",
        last_name="Employee",
        email=f"test_{uuid.uuid4().hex[:8]}@test.local",
        role_id=role.id,
        branch_id=branch.id,
        date_of_joining=date(2025, 1, 1),
        password_hash="$2b$12$placeholder_hash_for_tests_only",
        monthly_salary_paise=salary_paise,
        is_active=True,
    )
    session.add(emp)
    session.flush()
    return emp


def _seed_late_days(session, employee_id: uuid.UUID, year: int, month: int, count: int) -> None:
    """Insert `count` DailyAttendance rows with is_late=True for the 1st–Nth of the month."""
    for day in range(1, count + 1):
        session.add(DailyAttendance(
            employee_id=employee_id,
            date=date(year, month, day),
            status=AttendanceStatus.LATE,
            source=AttendanceSource.BIOMETRIC,
            is_late=True,
            late_minutes=15,
        ))
    session.flush()


def _set_policy(session) -> None:
    """Upsert the four payroll policy rows via plain INSERT (no pg-specific ON CONFLICT)."""
    from sqlalchemy import select
    from app.models.system import SystemPolicy

    for key, value in (
        ("payroll.late_days_per_unit", LATE_DAYS_PER_UNIT),
        ("payroll.penalty_percent_per_unit", PENALTY_PERCENT),
        ("payroll.grace_days", GRACE_DAYS),
        ("payroll.salary_days_per_month", SALARY_DAYS),
    ):
        existing = session.execute(
            select(SystemPolicy).where(SystemPolicy.key == key)
        ).scalar_one_or_none()
        if existing:
            existing.value = json.dumps(value)
        else:
            session.add(SystemPolicy(key=key, value=json.dumps(value)))
    session.flush()


# ── Test ───────────────────────────────────────────────────────────────────────

@patch("app.tasks.payroll._queue_payroll_notification")
def test_calculate_monthly_deductions_math(mock_notif, db_session):
    """12 lates, ₹30k salary → 0.5 day net × ₹1,000 = ₹500 (50000 paise)."""
    mock_notif.delay.return_value = None

    role = _make_role(db_session)
    branch = _make_branch(db_session)
    emp = _make_employee(db_session, role, branch)

    _seed_late_days(db_session, emp.id, TEST_YEAR, TEST_MONTH, LATE_DAYS)
    _set_policy(db_session)

    result = calculate_monthly_deductions(
        branch_id=None,
        year=TEST_YEAR,
        month=TEST_MONTH,
        session=db_session,     # pass session so the function does NOT commit
    )

    assert result["processed"] >= 1
    assert result["affected"] >= 1
    assert result["month"] == TEST_MONTH
    assert result["year"] == TEST_YEAR

    from sqlalchemy import select
    ded = db_session.execute(
        select(SalaryDeduction).where(
            SalaryDeduction.employee_id == emp.id,
            SalaryDeduction.month == TEST_MONTH,
            SalaryDeduction.year == TEST_YEAR,
        )
    ).scalar_one_or_none()

    assert ded is not None, "SalaryDeduction row must be created"
    assert ded.late_count == LATE_DAYS
    assert ded.penalty_units == EXPECTED_UNITS, f"units: expected {EXPECTED_UNITS}, got {ded.penalty_units}"
    assert ded.net_penalty_days_x100 == EXPECTED_NET_X100, (
        f"net_x100: expected {EXPECTED_NET_X100}, got {ded.net_penalty_days_x100}"
    )
    assert ded.daily_salary_paise == EXPECTED_DAILY
    assert ded.total_deduction_paise == EXPECTED_TOTAL, (
        f"MATH WRONG: expected {EXPECTED_TOTAL} paise (₹{EXPECTED_TOTAL/100}), "
        f"got {ded.total_deduction_paise} paise (₹{ded.total_deduction_paise/100})"
    )

    mock_notif.assert_called_once()
    call_args = mock_notif.call_args
    assert call_args.args[0] == str(emp.id)
    assert call_args.kwargs["late_count"] == LATE_DAYS
    assert call_args.kwargs["net_days"] == 0.5


@patch("app.tasks.payroll._queue_payroll_notification")
def test_no_deduction_when_within_grace(mock_notif, db_session):
    """
    7 late days → 2 units → 1.0 day gross, fully covered by the 1.5 grace days,
    so total_deduction_paise = 0 and NO notification.
    """
    mock_notif.delay.return_value = None

    role = _make_role(db_session)
    branch = _make_branch(db_session)
    emp = _make_employee(db_session, role, branch)

    _seed_late_days(db_session, emp.id, TEST_YEAR, TEST_MONTH, 7)  # 2 units = 1.0 day < 1.5 grace
    _set_policy(db_session)

    calculate_monthly_deductions(
        branch_id=None, year=TEST_YEAR, month=TEST_MONTH, session=db_session,
    )

    from sqlalchemy import select
    ded = db_session.execute(
        select(SalaryDeduction).where(
            SalaryDeduction.employee_id == emp.id,
            SalaryDeduction.month == TEST_MONTH,
            SalaryDeduction.year == TEST_YEAR,
        )
    ).scalar_one_or_none()

    assert ded is not None
    assert ded.late_count == 7
    assert ded.net_penalty_days_x100 == 0
    assert ded.total_deduction_paise == 0, (
        f"Zero deduction expected, got {ded.total_deduction_paise} paise"
    )
    mock_notif.assert_not_called()


@patch("app.tasks.payroll._queue_payroll_notification")
def test_branch_filter_isolates_employee(mock_notif, db_session):
    """When branch_id is supplied, only that branch's employees are processed."""
    mock_notif.delay.return_value = None

    role = _make_role(db_session)
    branch_a = _make_branch(db_session)
    branch_b = _make_branch(db_session)

    emp_a = _make_employee(db_session, role, branch_a)
    emp_b = _make_employee(db_session, role, branch_b)

    _seed_late_days(db_session, emp_a.id, TEST_YEAR, TEST_MONTH, LATE_DAYS)
    _seed_late_days(db_session, emp_b.id, TEST_YEAR, TEST_MONTH, LATE_DAYS)
    _set_policy(db_session)

    calculate_monthly_deductions(
        branch_id=branch_a.id, year=TEST_YEAR, month=TEST_MONTH, session=db_session,
    )

    from sqlalchemy import select
    ded_a = db_session.execute(
        select(SalaryDeduction).where(
            SalaryDeduction.employee_id == emp_a.id,
            SalaryDeduction.month == TEST_MONTH,
            SalaryDeduction.year == TEST_YEAR,
        )
    ).scalar_one_or_none()
    ded_b = db_session.execute(
        select(SalaryDeduction).where(
            SalaryDeduction.employee_id == emp_b.id,
            SalaryDeduction.month == TEST_MONTH,
            SalaryDeduction.year == TEST_YEAR,
        )
    ).scalar_one_or_none()

    assert ded_a is not None, "Branch A employee must have a deduction record"
    assert ded_a.total_deduction_paise == EXPECTED_TOTAL
    assert ded_b is None, "Branch B employee must NOT be processed when branch_id is set"
