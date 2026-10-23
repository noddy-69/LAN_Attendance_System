"""
Payroll router
==============
Endpoints:
  GET  /payroll/policy                  — read deduction policy
  PUT  /payroll/policy                  — update deduction policy
  POST /payroll/deductions/calculate    — calculate (or recalculate) deduction for employee-month
  GET  /payroll/deductions              — list salary deductions
  GET  /payroll/deductions/{id}         — get single deduction record
  GET  /payroll/reports/monthly         — download Excel (.xlsx) or CSV report

Monetary values: all paise fields are INTEGER throughout.
The Excel/CSV report converts to ₹ (÷100) only for human readability.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_permission
from app.models.employee import Employee
from app.schemas.common import ApiResponse
from app.schemas.payroll import (
    DeductionCalculateIn,
    DeductionPolicyIn,
    DeductionPolicyOut,
    SalaryDeductionOut,
)
from app.services import payroll_service

router = APIRouter(prefix="/payroll", tags=["payroll"])


# ── Serializer ────────────────────────────────────────────────────────────────

def _deduction_out(d) -> SalaryDeductionOut:
    return SalaryDeductionOut(
        id=d.id,
        employee_id=d.employee_id,
        employee_code=d.employee.employee_code,
        employee_name=f"{d.employee.first_name} {d.employee.last_name}",
        month=d.month,
        year=d.year,
        late_count=d.late_count,
        penalty_units=d.penalty_units,
        net_penalty_days=round((d.net_penalty_days_x100 or 0) / 100, 2),
        monthly_salary_paise=(d.monthly_salary_paise or 0),   # INTEGER paise
        daily_salary_paise=(d.daily_salary_paise or 0),       # INTEGER paise
        total_deduction_paise=d.total_deduction_paise,        # INTEGER paise
        notes=d.notes,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


# ── Policy endpoints ──────────────────────────────────────────────────────────

@router.get("/policy", response_model=ApiResponse[DeductionPolicyOut])
async def get_policy(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("payroll:read")),
):
    """Return the current late-penalty deduction policy."""
    policy = await payroll_service.get_policy(db)
    return ApiResponse.ok(policy)


@router.put("/policy", response_model=ApiResponse[DeductionPolicyOut])
async def update_policy(
    body: DeductionPolicyIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("payroll:write")),
):
    """
    Update the late-penalty policy.
    penalty_per_late_paise must be a positive INTEGER (e.g. ₹200 → 20000).
    """
    policy = await payroll_service.update_policy(db, body, actor_id=current_user.id)
    return ApiResponse.ok(policy)


# ── Deduction endpoints ───────────────────────────────────────────────────────

@router.post(
    "/deductions/calculate",
    response_model=ApiResponse[SalaryDeductionOut],
    status_code=201,
)
async def calculate_deduction(
    body: DeductionCalculateIn,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("payroll:write")),
):
    """
    Calculate (or recalculate) the monthly late-penalty deduction for one employee.
    Counts late days from daily_attendance, upserts salary_deductions.
    total_deduction_paise is stored as INTEGER paise.
    """
    ded = await payroll_service.calculate_deduction(
        db, body.employee_id, body.month, body.year
    )
    return ApiResponse.ok(_deduction_out(ded))


@router.get("/deductions", response_model=ApiResponse[list[SalaryDeductionOut]])
async def list_deductions(
    employee_id: uuid.UUID | None = Query(default=None),
    month: int | None = Query(default=None, ge=1, le=12),
    year: int | None = Query(default=None, ge=2020, le=2100),
    per_page: int = Query(default=30, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("payroll:read")),
):
    """List salary deduction records with optional filters."""
    records, pagination = await payroll_service.list_deductions(
        db,
        employee_id=employee_id,
        month=month,
        year=year,
        per_page=per_page,
        cursor=cursor,
    )
    return ApiResponse.ok([_deduction_out(r) for r in records], pagination)


@router.get("/deductions/report")
async def download_deduction_report(
    month: str = Query(
        description="Month in YYYY-MM format (e.g. 2026-06)",
    ),
    branch_id: uuid.UUID | None = Query(default=None),
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("payroll:read")),
):
    """
    Download the monthly payroll deduction report as Excel (.xlsx) or CSV.

    Columns: Employee Code, Name, Days Present, Days Absent, Days on Leave,
    Late Count, Allowed Lates, Excess Lates, Penalty per Late (₹), Total Deduction (₹)

    A TOTAL sum row is appended at the bottom of the Excel file.
    Monetary columns are in ₹ (rupees), not paise.

    ?month=YYYY-MM   — required, e.g. 2026-06
    ?branch_id=UUID  — optional; limits to employees of that branch
    ?format=xlsx|csv — default xlsx
    """
    try:
        year_int, month_int = (int(p) for p in month.split("-"))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format, e.g. 2026-06",
        )
    if not (1 <= month_int <= 12) or year_int < 2020:
        raise HTTPException(
            status_code=422,
            detail="month must be a valid calendar month and year >= 2020",
        )

    filename_base = f"payroll_{year_int}_{month_int:02d}"

    if format == "xlsx":
        data = await payroll_service.generate_excel_report(
            db, month_int, year_int, branch_id=branch_id
        )
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
        )

    data = await payroll_service.generate_csv_report(
        db, month_int, year_int, branch_id=branch_id
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
    )


@router.get(
    "/deductions/{deduction_id}",
    response_model=ApiResponse[SalaryDeductionOut],
)
async def get_deduction(
    deduction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("payroll:read")),
):
    """Fetch a single salary deduction record."""
    ded = await payroll_service.get_deduction(db, deduction_id)
    return ApiResponse.ok(_deduction_out(ded))


# ── Report download ───────────────────────────────────────────────────────────

@router.get("/reports/monthly")
async def download_monthly_report(
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2020, le=2100),
    branch_id: uuid.UUID | None = Query(default=None),
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("payroll:read")),
):
    """
    Download the monthly payroll deduction report.
    format=xlsx (default) returns an Excel file.
    format=csv returns a UTF-8 BOM CSV for direct Excel import.
    Monetary columns show ₹ values (paise ÷ 100) — for human readability only.
    """
    filename_base = f"payroll_{year}_{month:02d}"

    if format == "xlsx":
        data = await payroll_service.generate_excel_report(
            db, month, year, branch_id=branch_id
        )
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'
            },
        )

    data = await payroll_service.generate_csv_report(
        db, month, year, branch_id=branch_id
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_base}.csv"'
        },
    )
