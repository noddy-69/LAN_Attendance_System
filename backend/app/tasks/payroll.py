"""
Payroll Task — calculate_monthly_deductions
==========================================
Core synchronous function for computing monthly late-penalty deductions.

Called by:
  - app.tasks.payroll_tasks.run_monthly_payroll  (Celery beat)
  - integration tests (passing an explicit session)

Design
------
  • All monetary values stored as INTEGER paise (1 ₹ = 100 paise).
  • No float arithmetic anywhere in the deduction path.
  • Affected employees (excess_late_count > 0) receive a PAYROLL_DEDUCTION
    notification queued via Celery (WhatsApp → email → in-app cascade).

Session contract
----------------
  session=None  → function creates its own session, commits, closes.
  session=<obj> → function flushes but does NOT commit; caller owns the
                  transaction.  Use this form in tests to enable rollback.
"""

from __future__ import annotations

import calendar
import json
import logging
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.daily_attendance import DailyAttendance
from app.models.employee import Employee
from app.models.payroll import SalaryDeduction
from app.models.role import Role
from app.models.system import SystemPolicy
from app.utils.payroll_calc import DeductionPolicy, compute_deduction

log = logging.getLogger(__name__)

_POLICY_LATE_DAYS_PER_UNIT = "payroll.late_days_per_unit"
_POLICY_PENALTY_PERCENT = "payroll.penalty_percent_per_unit"
_POLICY_GRACE_DAYS = "payroll.grace_days"
_POLICY_SALARY_DAYS = "payroll.salary_days_per_month"

_sync_factory: sessionmaker | None = None


def _queue_payroll_notification(employee_id: str, **kwargs) -> None:
    """
    Thin wrapper around send_notification.delay — isolated here so tests can
    patch app.tasks.payroll._queue_payroll_notification without needing to
    import the Celery task module.
    """
    from app.tasks.notifications import send_notification
    send_notification.delay(employee_id, "PAYROLL_DEDUCTION", **kwargs)


def _get_factory() -> sessionmaker:
    global _sync_factory
    if _sync_factory is None:
        url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        _sync_factory = sessionmaker(
            bind=create_engine(url, pool_size=3, pool_pre_ping=True),
            expire_on_commit=False,
        )
    return _sync_factory


def _policy_raw(session: Session, key: str):
    return session.execute(
        select(SystemPolicy.value).where(
            SystemPolicy.key == key,
            SystemPolicy.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


def _policy_int(session: Session, key: str, default: int) -> int:
    row = _policy_raw(session, key)
    if row is None:
        return default
    try:
        return int(json.loads(row))
    except (TypeError, ValueError):
        return default


def _policy_float(session: Session, key: str, default: float) -> float:
    row = _policy_raw(session, key)
    if row is None:
        return default
    try:
        return float(json.loads(row))
    except (TypeError, ValueError):
        return default


def _run(
    session: Session,
    branch_id: uuid.UUID | None,
    year: int,
    month: int,
) -> dict:
    """
    Inner logic executed against an already-open session.
    Flushes at the end; does NOT commit.
    """
    policy = DeductionPolicy(
        late_days_per_unit=_policy_int(session, _POLICY_LATE_DAYS_PER_UNIT, settings.DEFAULT_LATE_DAYS_PER_UNIT),
        penalty_percent_per_unit=_policy_int(session, _POLICY_PENALTY_PERCENT, settings.DEFAULT_PENALTY_PERCENT_PER_UNIT),
        grace_days=_policy_float(session, _POLICY_GRACE_DAYS, settings.DEFAULT_GRACE_DAYS),
        salary_days_per_month=_policy_int(session, _POLICY_SALARY_DAYS, settings.DEFAULT_SALARY_DAYS_PER_MONTH),
    )

    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    now_str = datetime.now(timezone.utc).date().isoformat()
    month_name = calendar.month_name[month]

    emp_stmt = select(Employee).where(
        Employee.is_active.is_(True),
        Employee.deleted_at.is_(None),
        ~Employee.role.has(Role.name == "service"),
    )
    if branch_id is not None:
        emp_stmt = emp_stmt.where(Employee.branch_id == branch_id)

    employees = session.execute(emp_stmt).scalars().all()

    processed = 0
    affected = 0

    for emp in employees:
        late_count: int = session.execute(
            select(func.count()).where(
                DailyAttendance.employee_id == emp.id,
                DailyAttendance.date >= first_day,
                DailyAttendance.date <= last_day,
                DailyAttendance.is_late.is_(True),
                DailyAttendance.deleted_at.is_(None),
            )
        ).scalar_one()

        monthly_salary = emp.monthly_salary_paise or 0
        calc = compute_deduction(late_count, monthly_salary, policy)
        total_paise = calc["total_deduction_paise"]

        existing = session.execute(
            select(SalaryDeduction).where(
                SalaryDeduction.employee_id == emp.id,
                SalaryDeduction.month == month,
                SalaryDeduction.year == year,
            )
        ).scalar_one_or_none()

        if existing:
            existing.late_count = late_count
            existing.monthly_salary_paise = monthly_salary
            existing.daily_salary_paise = calc["daily_salary_paise"]
            existing.penalty_units = calc["penalty_units"]
            existing.net_penalty_days_x100 = calc["net_penalty_days_x100"]
            existing.total_deduction_paise = total_paise
            existing.notes = f"Recalculated {now_str}"
        else:
            session.add(SalaryDeduction(
                employee_id=emp.id,
                month=month,
                year=year,
                late_count=late_count,
                monthly_salary_paise=monthly_salary,
                daily_salary_paise=calc["daily_salary_paise"],
                penalty_units=calc["penalty_units"],
                net_penalty_days_x100=calc["net_penalty_days_x100"],
                total_deduction_paise=total_paise,
                notes=f"Calculated {now_str}",
            ))

        processed += 1

        if total_paise > 0:
            affected += 1
            _queue_payroll_notification(
                str(emp.id),
                amount=round(total_paise / 100, 2),
                month=month_name,
                year=year,
                late_count=late_count,
                net_days=round(calc["net_penalty_days_x100"] / 100, 2),
            )
            log.info(
                "PAYROLL_DEDUCTION queued: employee=%s late=%d total_paise=%d",
                emp.id, late_count, total_paise,
            )

    session.flush()
    log.info(
        "calculate_monthly_deductions: branch=%s %d/%d processed=%d affected=%d",
        branch_id, month, year, processed, affected,
    )
    return {"processed": processed, "affected": affected, "month": month, "year": year}


def calculate_monthly_deductions(
    branch_id: Optional[uuid.UUID],
    year: int,
    month: int,
    session: Optional[Session] = None,
) -> dict:
    """
    Calculate late-penalty deductions for all active employees in a branch
    (or all branches when branch_id is None) for the given month/year.

    Parameters
    ----------
    branch_id : Filter to a single branch; None processes every branch.
    year      : Calendar year (e.g. 2026).
    month     : Calendar month 1–12.
    session   : Provide an open SQLAlchemy Session for tests (caller rolls back).
                Omit in production; the function opens and commits its own.

    Returns
    -------
    dict with keys: processed, affected, month, year
    """
    if session is not None:
        # Caller-managed session: flush only, no commit.
        return _run(session, branch_id, year, month)

    # Production path: own session, commit + close.
    with _get_factory()() as own_session:
        result = _run(own_session, branch_id, year, month)
        own_session.commit()
    return result
