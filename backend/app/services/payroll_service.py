"""
Payroll Service
===============
Manages the deduction policy (system_policies table) and monthly
late-penalty records (salary_deductions table).

Money rule: all monetary values are INTEGER paise throughout.
The only paise→rupee conversion is inside the Excel/CSV report
generators for human-readable output.
"""
import csv
import io
import json
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.daily_attendance import AttendanceStatus, DailyAttendance
from app.models.employee import Employee
from app.models.payroll import SalaryDeduction
from app.models.role import Role
from app.models.system import SystemPolicy
from app.schemas.common import PaginationMeta
from app.schemas.payroll import DeductionPolicyIn, DeductionPolicyOut
from app.utils.pagination import paginate
from app.utils.payroll_calc import DeductionPolicy, compute_deduction

# Percentage-of-a-day deduction policy keys (system_policies).
_POLICY_LATE_DAYS_PER_UNIT = "payroll.late_days_per_unit"
_POLICY_PENALTY_PERCENT = "payroll.penalty_percent_per_unit"
_POLICY_GRACE_DAYS = "payroll.grace_days"
_POLICY_SALARY_DAYS = "payroll.salary_days_per_month"

_EAGER = [selectinload(SalaryDeduction.employee)]


# ── Policy helpers ────────────────────────────────────────────────────────────

async def _policy_raw(db: AsyncSession, key: str):
    result = await db.execute(
        select(SystemPolicy.value).where(
            SystemPolicy.key == key,
            SystemPolicy.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _policy_int(db: AsyncSession, key: str, default: int) -> int:
    raw = await _policy_raw(db, key)
    if raw is None:
        return default
    try:
        return int(json.loads(raw))
    except (ValueError, TypeError):
        return default


async def _policy_float(db: AsyncSession, key: str, default: float) -> float:
    raw = await _policy_raw(db, key)
    if raw is None:
        return default
    try:
        return float(json.loads(raw))
    except (ValueError, TypeError):
        return default


async def get_policy(db: AsyncSession) -> DeductionPolicyOut:
    return DeductionPolicyOut(
        late_days_per_unit=await _policy_int(
            db, _POLICY_LATE_DAYS_PER_UNIT, settings.DEFAULT_LATE_DAYS_PER_UNIT),
        penalty_percent_per_unit=await _policy_int(
            db, _POLICY_PENALTY_PERCENT, settings.DEFAULT_PENALTY_PERCENT_PER_UNIT),
        grace_days=await _policy_float(
            db, _POLICY_GRACE_DAYS, settings.DEFAULT_GRACE_DAYS),
        salary_days_per_month=await _policy_int(
            db, _POLICY_SALARY_DAYS, settings.DEFAULT_SALARY_DAYS_PER_MONTH),
    )


async def _policy_obj(db: AsyncSession) -> DeductionPolicy:
    p = await get_policy(db)
    return DeductionPolicy(
        late_days_per_unit=p.late_days_per_unit,
        penalty_percent_per_unit=p.penalty_percent_per_unit,
        grace_days=p.grace_days,
        salary_days_per_month=p.salary_days_per_month,
    )


async def update_policy(
    db: AsyncSession,
    data: DeductionPolicyIn,
    actor_id: uuid.UUID,
) -> DeductionPolicyOut:
    for key, value in (
        (_POLICY_LATE_DAYS_PER_UNIT, data.late_days_per_unit),
        (_POLICY_PENALTY_PERCENT, data.penalty_percent_per_unit),
        (_POLICY_GRACE_DAYS, data.grace_days),
        (_POLICY_SALARY_DAYS, data.salary_days_per_month),
    ):
        stmt = (
            pg_insert(SystemPolicy)
            .values(
                id=uuid.uuid4(),
                key=key,
                value=json.dumps(value),
                updated_by_id=actor_id,
            )
            .on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "value": json.dumps(value),
                    "updated_by_id": actor_id,
                    "updated_at": func.now(),
                },
            )
        )
        await db.execute(stmt)
    await db.flush()
    return await get_policy(db)


# ── Deduction calculation ─────────────────────────────────────────────────────

async def calculate_deduction(
    db: AsyncSession,
    employee_id: uuid.UUID,
    month: int,
    year: int,
) -> SalaryDeduction:
    """
    Count late days for employee-month, compute penalty, upsert salary_deductions.
    All amounts stored as INTEGER paise — no float arithmetic.
    """
    emp_result = await db.execute(
        select(Employee).where(
            Employee.id == employee_id,
            Employee.deleted_at.is_(None),
        )
    )
    emp = emp_result.scalar_one_or_none()
    if emp is None:
        raise NotFoundError(f"Employee {employee_id} not found")

    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    count_result = await db.execute(
        select(func.count()).where(
            DailyAttendance.employee_id == employee_id,
            DailyAttendance.date >= first_day,
            DailyAttendance.date <= last_day,
            DailyAttendance.is_late.is_(True),
            DailyAttendance.deleted_at.is_(None),
        )
    )
    late_count: int = count_result.scalar_one()

    policy = await _policy_obj(db)
    monthly_salary = emp.monthly_salary_paise or 0
    calc = compute_deduction(late_count, monthly_salary, policy)
    total_paise = calc["total_deduction_paise"]

    common = dict(
        late_count=late_count,
        monthly_salary_paise=monthly_salary,
        daily_salary_paise=calc["daily_salary_paise"],
        penalty_units=calc["penalty_units"],
        net_penalty_days_x100=calc["net_penalty_days_x100"],
        total_deduction_paise=total_paise,
    )
    upsert = (
        pg_insert(SalaryDeduction)
        .values(
            id=uuid.uuid4(),
            employee_id=employee_id,
            month=month,
            year=year,
            notes=f"Calculated {datetime.now(timezone.utc).date().isoformat()}",
            **common,
        )
        .on_conflict_do_update(
            constraint="uq_salary_deduction_employee_month_year",
            set_={
                **common,
                "notes": f"Recalculated {datetime.now(timezone.utc).date().isoformat()}",
                "updated_at": func.now(),
            },
        )
    )
    await db.execute(upsert)
    await db.flush()

    result = await db.execute(
        select(SalaryDeduction)
        .where(
            SalaryDeduction.employee_id == employee_id,
            SalaryDeduction.month == month,
            SalaryDeduction.year == year,
        )
        .options(*_EAGER)
        .execution_options(populate_existing=True)
    )
    record = result.scalar_one()

    if total_paise > 0:
        import calendar as _cal
        from app.tasks.payroll import _queue_payroll_notification
        _queue_payroll_notification(
            str(employee_id),
            amount=round(total_paise / 100, 2),
            month=_cal.month_name[month],
            year=year,
            late_count=late_count,
            net_days=round(calc["net_penalty_days_x100"] / 100, 2),
        )

    return record


# ── Query helpers ─────────────────────────────────────────────────────────────

async def list_deductions(
    db: AsyncSession,
    *,
    employee_id: uuid.UUID | None = None,
    month: int | None = None,
    year: int | None = None,
    per_page: int = 30,
    cursor: str | None = None,
) -> tuple[list[SalaryDeduction], PaginationMeta]:
    stmt = (
        select(SalaryDeduction)
        .where(SalaryDeduction.deleted_at.is_(None))
        .options(*_EAGER)
    )
    if employee_id:
        stmt = stmt.where(SalaryDeduction.employee_id == employee_id)
    if month:
        stmt = stmt.where(SalaryDeduction.month == month)
    if year:
        stmt = stmt.where(SalaryDeduction.year == year)
    return await paginate(db, stmt, SalaryDeduction, per_page, cursor)


async def get_deduction(db: AsyncSession, deduction_id: uuid.UUID) -> SalaryDeduction:
    result = await db.execute(
        select(SalaryDeduction)
        .where(
            SalaryDeduction.id == deduction_id,
            SalaryDeduction.deleted_at.is_(None),
        )
        .options(*_EAGER)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise NotFoundError(f"Salary deduction {deduction_id} not found")
    return record


# ── Report helpers ────────────────────────────────────────────────────────────

async def _monthly_stats(
    db: AsyncSession,
    employee_id: uuid.UUID,
    month: int,
    year: int,
) -> dict:
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    result = await db.execute(
        select(DailyAttendance.status, DailyAttendance.is_late)
        .where(
            DailyAttendance.employee_id == employee_id,
            DailyAttendance.date >= first_day,
            DailyAttendance.date <= last_day,
            DailyAttendance.deleted_at.is_(None),
        )
    )
    rows = result.all()

    present_statuses = {AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.HALF_DAY}
    return {
        "days_present": sum(1 for r in rows if r.status in present_statuses),
        "days_absent":  sum(1 for r in rows if r.status == AttendanceStatus.ABSENT),
        "days_on_leave": sum(1 for r in rows if r.status == AttendanceStatus.ON_LEAVE),
        "late_count":   sum(1 for r in rows if r.is_late),
    }


def _report_headers() -> list[str]:
    return [
        "Employee Code",
        "Name",
        "Days Present",
        "Days Absent",
        "Days on Leave",
        "Late Count",
        "Penalty Units",
        "Net Penalty Days",
        "Monthly Salary (₹)",
        "Daily Salary (₹)",
        "Total Deduction (₹)",
    ]


async def _report_rows(
    db: AsyncSession,
    month: int,
    year: int,
    branch_id: uuid.UUID | None = None,
) -> tuple[str, list[list]]:
    """Return (month_name, list_of_data_rows) for use in both Excel and CSV."""
    import calendar
    month_name = calendar.month_name[month]
    policy = await _policy_obj(db)

    emp_stmt = (
        select(Employee)
        .where(
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
            ~Employee.role.has(Role.name == "service"),
        )
        .order_by(Employee.employee_code)
    )
    if branch_id:
        emp_stmt = emp_stmt.where(Employee.branch_id == branch_id)

    emp_result = await db.execute(emp_stmt)
    employees: list[Employee] = list(emp_result.scalars().all())

    ded_result = await db.execute(
        select(SalaryDeduction).where(
            SalaryDeduction.month == month,
            SalaryDeduction.year == year,
            SalaryDeduction.deleted_at.is_(None),
        )
    )
    ded_map: dict[uuid.UUID, SalaryDeduction] = {
        d.employee_id: d for d in ded_result.scalars().all()
    }

    rows = []
    for emp in employees:
        stats = await _monthly_stats(db, emp.id, month, year)
        ded = ded_map.get(emp.id)

        if ded and ded.daily_salary_paise is not None:
            late_count = ded.late_count
            units = ded.penalty_units
            net_x100 = ded.net_penalty_days_x100
            monthly_paise = ded.monthly_salary_paise or emp.monthly_salary_paise
            daily_paise = ded.daily_salary_paise
            total_paise = ded.total_deduction_paise
        else:
            late_count = stats["late_count"]
            monthly_paise = emp.monthly_salary_paise or 0
            calc = compute_deduction(late_count, monthly_paise, policy)
            units = calc["penalty_units"]
            net_x100 = calc["net_penalty_days_x100"]
            daily_paise = calc["daily_salary_paise"]
            total_paise = calc["total_deduction_paise"]

        rows.append([
            emp.employee_code,
            f"{emp.first_name} {emp.last_name}",
            stats["days_present"],
            stats["days_absent"],
            stats["days_on_leave"],
            late_count,
            units,
            round(net_x100 / 100, 2),
            round((monthly_paise or 0) / 100, 2),   # paise → ₹ for human display
            round(daily_paise / 100, 2),
            round(total_paise / 100, 2),
        ])
    return month_name, rows


async def generate_excel_report(
    db: AsyncSession,
    month: int,
    year: int,
    branch_id: uuid.UUID | None = None,
) -> bytes:
    """Generate .xlsx payroll report. Returns raw bytes for HTTP response."""
    month_name, data_rows = await _report_rows(db, month, year, branch_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{month_name} {year}"

    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    center = Alignment(horizontal="center", vertical="center")
    bold = Font(bold=True)
    total_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

    headers = _report_headers()
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center

    for row_idx, row in enumerate(data_rows, start=2):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Total sum row
    if data_rows:
        total_row = len(data_rows) + 2
        # TOTAL label in first cell
        lbl = ws.cell(row=total_row, column=1, value="TOTAL")
        lbl.font = bold
        lbl.fill = total_fill
        # Columns by index: 3=Days Present, 4=Days Absent, 5=Days on Leave,
        # 6=Late Count, 7=Penalty Units, 8=Net Penalty Days, 9=Monthly Salary,
        # 10=Daily Salary, 11=Total Deduction. Sum the count + money totals.
        for col_idx in (3, 4, 5, 6, 7, 11):
            col_letter = ws.cell(row=1, column=col_idx).column_letter
            cell = ws.cell(
                row=total_row,
                column=col_idx,
                value=f"=SUM({col_letter}2:{col_letter}{total_row - 1})",
            )
            cell.font = bold
            cell.fill = total_fill
        # Fill remaining total row cells
        for col_idx in (2, 8, 9, 10):
            ws.cell(row=total_row, column=col_idx).fill = total_fill

    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


async def generate_csv_report(
    db: AsyncSession,
    month: int,
    year: int,
    branch_id: uuid.UUID | None = None,
) -> bytes:
    """Generate CSV payroll report. Returns UTF-8 BOM bytes for Excel compatibility."""
    _, data_rows = await _report_rows(db, month, year, branch_id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_report_headers())
    writer.writerows(data_rows)

    return buf.getvalue().encode("utf-8-sig")
