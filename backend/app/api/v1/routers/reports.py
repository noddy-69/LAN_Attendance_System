"""
Reports router
==============
Downloadable data exports for HR and management.

Endpoints:
  GET /reports/attendance   — attendance CSV or Excel
  GET /reports/leave        — leave request CSV or Excel
  GET /reports/payroll      — payroll deduction Excel or CSV
                              (delegates to payroll_service)

Column specs from CLAUDE.md:

Attendance:
  Employee Name, Employee Code, Date, Check-In (IST), Check-Out (IST),
  Work Hours, Status, Is Late, Late Minutes, Overtime Minutes, Source

Leave:
  Employee Name, Employee Code, Leave Type, Leave Code, Start Date,
  End Date, Days, Status, Reason, Manager, Manager Action Date,
  Manager Remarks, HR, HR Action Date, HR Remarks, Applied At

Payroll (see payroll router /payroll/reports/monthly for primary path):
  Employee Name, Employee Code, Month, Year, Days Present, Days Absent,
  Days on Leave, Late Count, Allowed Lates, Excess Lates,
  Penalty per Late (Rs), Total Deduction (Rs), Net Deduction (Rs)

IST note: DB timestamps are UTC; check-in/check-out are displayed in IST.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_permission
from app.models.daily_attendance import AttendanceStatus
from app.models.employee import Employee
from app.models.leave import LeaveStatus
from app.services import payroll_service, report_service

router = APIRouter(prefix="/reports", tags=["reports"])


# ── Attendance report ─────────────────────────────────────────────────────────

@router.get("/attendance/export")
async def attendance_export(
    start: date | None = Query(default=None, alias="start"),
    end: date | None = Query(default=None, alias="end"),
    employee_id: uuid.UUID | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    status: AttendanceStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("attendance:read")),
):
    """
    CSV export of attendance records.  Alias endpoint with ?start=&end= params.

    Columns (in order): Employee Code, Employee Name, Date, Check In, Check Out,
    Work Hours, Late, Late Minutes, Overtime, Status, Source

    Timestamps are in IST.  No monetary fields.
    """
    fname = f"attendance_{start or 'all'}_{end or 'all'}"
    data = await report_service.generate_attendance_csv(
        db,
        from_date=start,
        to_date=end,
        employee_id=employee_id,
        branch_id=branch_id,
        status=status,
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
    )


@router.get("/attendance")
async def attendance_report(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    employee_id: uuid.UUID | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    status: AttendanceStatus | None = Query(default=None),
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("attendance:read")),
):
    """
    Download attendance records.

    Columns: Employee Name, Employee Code, Date, Check-In (IST),
    Check-Out (IST), Work Hours, Status, Is Late, Late Minutes,
    Overtime Minutes, Source

    Filters: from_date / to_date, employee_id, branch_id, status
    format=xlsx (default) or format=csv
    """
    fname = f"attendance_{from_date or 'all'}_{to_date or 'all'}"

    if format == "xlsx":
        data = await report_service.generate_attendance_excel(
            db,
            from_date=from_date,
            to_date=to_date,
            employee_id=employee_id,
            branch_id=branch_id,
            status=status,
        )
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'},
        )

    data = await report_service.generate_attendance_csv(
        db,
        from_date=from_date,
        to_date=to_date,
        employee_id=employee_id,
        branch_id=branch_id,
        status=status,
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
    )


# ── Leave report ──────────────────────────────────────────────────────────────

@router.get("/leave/export")
async def leave_export(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    employee_id: uuid.UUID | None = Query(default=None),
    status: LeaveStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:read")),
):
    """
    CSV export of leave requests.

    Columns include: Employee Name, Employee Code, Leave Type, Start Date,
    End Date, Days, Status (plus full audit trail columns).
    """
    fname = f"leave_{from_date or 'all'}_{to_date or 'all'}"
    data = await report_service.generate_leave_csv(
        db,
        from_date=from_date,
        to_date=to_date,
        employee_id=employee_id,
        status=status,
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
    )


@router.get("/leave")
async def leave_report(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    employee_id: uuid.UUID | None = Query(default=None),
    status: LeaveStatus | None = Query(default=None),
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:read")),
):
    """
    Download leave requests.

    Columns: Employee Name, Employee Code, Leave Type, Leave Code,
    Start Date, End Date, Days, Status, Reason, Manager,
    Manager Action Date, Manager Remarks, HR, HR Action Date,
    HR Remarks, Applied At

    Filters: from_date / to_date (start_date range), employee_id, status
    format=xlsx (default) or format=csv
    """
    fname = f"leave_{from_date or 'all'}_{to_date or 'all'}"

    if format == "xlsx":
        data = await report_service.generate_leave_excel(
            db,
            from_date=from_date,
            to_date=to_date,
            employee_id=employee_id,
            status=status,
        )
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'},
        )

    data = await report_service.generate_leave_csv(
        db,
        from_date=from_date,
        to_date=to_date,
        employee_id=employee_id,
        status=status,
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
    )


# ── Payroll report ────────────────────────────────────────────────────────────

@router.get("/payroll")
async def payroll_report(
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2020, le=2100),
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("payroll:read")),
):
    """
    Download the monthly payroll deduction report.

    Columns: Employee Name, Employee Code, Month, Year, Days Present,
    Days Absent, Days on Leave, Late Count, Allowed Lates, Excess Lates,
    Penalty per Late (Rs), Total Deduction (Rs), Net Deduction (Rs)

    Monetary columns show Rs values (paise ÷ 100) for human readability.
    format=xlsx (default) or format=csv
    """
    fname = f"payroll_{year}_{month:02d}"

    if format == "xlsx":
        data = await payroll_service.generate_excel_report(db, month, year)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'},
        )

    data = await payroll_service.generate_csv_report(db, month, year)
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
    )
