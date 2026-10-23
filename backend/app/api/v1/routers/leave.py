import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import is_hr_tier, require_hr_tier_final_approval, require_permission
from app.core.scoping import assert_can_act_on, visible_employee_ids
from app.models.employee import Employee
from app.models.leave import LeaveBalance, LeaveRequest, LeaveStatus
from app.schemas.common import ApiResponse
from app.schemas.leave import (
    LeaveActionIn,
    LeaveApplyIn,
    LeaveBalanceAdjustIn,
    LeaveBalanceOut,
    LeaveRequestOut,
    LeaveTypeCreate,
    LeaveTypeOut,
    LeaveTypeUpdate,
)
from app.services import leave_service

router = APIRouter(prefix="/leave", tags=["leave"])


# ── Serialisers ───────────────────────────────────────────────────────────────

def _type_out(lt) -> LeaveTypeOut:
    return LeaveTypeOut(
        id=lt.id,
        name=lt.name,
        code=lt.code,
        days_per_year=lt.days_per_year,
        is_paid=lt.is_paid,
        requires_approval=lt.requires_approval,
        carry_forward=lt.carry_forward,
        max_carry_forward_days=lt.max_carry_forward_days,
        description=lt.description,
        created_at=lt.created_at,
    )


def _request_out(req: LeaveRequest) -> LeaveRequestOut:
    def _name(emp) -> str | None:
        return f"{emp.first_name} {emp.last_name}" if emp else None

    return LeaveRequestOut(
        id=req.id,
        employee_id=req.employee_id,
        employee_name=_name(req.employee) or "",
        leave_type_id=req.leave_type_id,
        leave_type_name=req.leave_type.name if req.leave_type else "",
        leave_type_code=req.leave_type.code if req.leave_type else "",
        start_date=req.start_date,
        end_date=req.end_date,
        days_requested=float(req.days_requested),
        is_half_day=req.is_half_day,
        reason=req.reason,
        status=req.status,
        manager_id=req.manager_id,
        manager_name=_name(req.approving_manager),
        manager_action_at=req.manager_action_at,
        manager_remarks=req.manager_remarks,
        hr_id=req.hr_id,
        hr_name=_name(req.approving_hr),
        hr_action_at=req.hr_action_at,
        hr_remarks=req.hr_remarks,
        created_at=req.created_at,
        updated_at=req.updated_at,
    )


def _balance_out(bal: LeaveBalance) -> LeaveBalanceOut:
    return LeaveBalanceOut(
        id=bal.id,
        employee_id=bal.employee_id,
        leave_type_id=bal.leave_type_id,
        leave_type_name=bal.leave_type.name if bal.leave_type else "",
        leave_type_code=bal.leave_type.code if bal.leave_type else "",
        year=bal.year,
        allocated_days=bal.allocated_days,
        carried_forward_days=bal.carried_forward_days,
        used_days=bal.used_days,
        available_days=bal.allocated_days + bal.carried_forward_days - bal.used_days,
    )


# ── Leave types ───────────────────────────────────────────────────────────────

@router.get("/types", response_model=ApiResponse[list[LeaveTypeOut]])
async def list_leave_types(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:read")),
):
    types = await leave_service.list_leave_types(db)
    return ApiResponse.ok([_type_out(t) for t in types])


@router.post("/types", response_model=ApiResponse[LeaveTypeOut], status_code=201)
async def create_leave_type(
    body: LeaveTypeCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:write")),
):
    lt = await leave_service.create_leave_type(db, body)
    return ApiResponse.ok(_type_out(lt))


@router.get("/types/{lt_id}", response_model=ApiResponse[LeaveTypeOut])
async def get_leave_type(
    lt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:read")),
):
    lt = await leave_service.get_leave_type(db, lt_id)
    return ApiResponse.ok(_type_out(lt))


@router.patch("/types/{lt_id}", response_model=ApiResponse[LeaveTypeOut])
async def update_leave_type(
    lt_id: uuid.UUID,
    body: LeaveTypeUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:write")),
):
    lt = await leave_service.update_leave_type(db, lt_id, body)
    return ApiResponse.ok(_type_out(lt))


@router.delete("/types/{lt_id}", response_model=ApiResponse[None])
async def delete_leave_type(
    lt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:write")),
):
    await leave_service.delete_leave_type(db, lt_id)
    return ApiResponse.ok(None)


# ── Leave requests ────────────────────────────────────────────────────────────

@router.post("/apply", response_model=ApiResponse[LeaveRequestOut], status_code=201)
async def apply(
    body: LeaveApplyIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("leave:write")),
):
    req = await leave_service.apply(db, current_user.id, body)
    return ApiResponse.ok(_request_out(req))


@router.get("/requests", response_model=ApiResponse[list[LeaveRequestOut]])
async def list_requests(
    employee_id: uuid.UUID | None = Query(default=None),
    status: LeaveStatus | None = Query(default=None),
    leave_type_id: uuid.UUID | None = Query(default=None),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    per_page: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("leave:read")),
):
    # Managers see only their department's employees; HR/Admin see all; employees see own.
    scope = await visible_employee_ids(db, current_user)
    requests, pagination = await leave_service.list_requests(
        db,
        employee_id=(employee_id if scope is None else None),
        employee_ids=scope,
        status=status,
        leave_type_id=leave_type_id,
        from_date=from_date,
        to_date=to_date,
        per_page=per_page,
        cursor=cursor,
    )
    return ApiResponse.ok([_request_out(r) for r in requests], pagination)


@router.get("/requests/{request_id}", response_model=ApiResponse[LeaveRequestOut])
async def get_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:read")),
):
    req = await leave_service.get_request(db, request_id)
    return ApiResponse.ok(_request_out(req))


@router.post(
    "/requests/{request_id}/manager-approve",
    response_model=ApiResponse[LeaveRequestOut],
)
async def manager_approve(
    request_id: uuid.UUID,
    body: LeaveActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("leave:approve")),
):
    # A manager may only act on requests from their own department.
    existing = await leave_service.get_request(db, request_id)
    await assert_can_act_on(db, current_user, existing.employee_id)
    req = await leave_service.manager_approve(
        db, request_id, current_user.id, body.remarks
    )
    return ApiResponse.ok(_request_out(req))


@router.post(
    "/requests/{request_id}/manager-reject",
    response_model=ApiResponse[LeaveRequestOut],
)
async def manager_reject(
    request_id: uuid.UUID,
    body: LeaveActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("leave:approve")),
):
    existing = await leave_service.get_request(db, request_id)
    await assert_can_act_on(db, current_user, existing.employee_id)
    req = await leave_service.reject(
        db, request_id, current_user.id, is_hr=False, remarks=body.remarks
    )
    return ApiResponse.ok(_request_out(req))


@router.post(
    "/requests/{request_id}/hr-approve",
    response_model=ApiResponse[LeaveRequestOut],
)
async def hr_approve(
    request_id: uuid.UUID,
    body: LeaveActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("leave:approve")),
):
    # Final approval is HR/Admin only. They may approve a request still at the
    # manager stage (direct finalize); managers use manager-approve instead.
    require_hr_tier_final_approval(current_user)
    req = await leave_service.hr_approve(
        db, request_id, current_user.id, body.remarks
    )
    return ApiResponse.ok(_request_out(req))


@router.post(
    "/requests/{request_id}/hr-reject",
    response_model=ApiResponse[LeaveRequestOut],
)
async def hr_reject(
    request_id: uuid.UUID,
    body: LeaveActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("leave:approve")),
):
    req = await leave_service.reject(
        db, request_id, current_user.id, is_hr=True, remarks=body.remarks
    )
    return ApiResponse.ok(_request_out(req))


@router.post(
    "/requests/{request_id}/cancel",
    response_model=ApiResponse[LeaveRequestOut],
)
async def cancel(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("leave:write")),
):
    req = await leave_service.cancel(
        db, request_id, current_user.id, is_privileged=is_hr_tier(current_user)
    )
    return ApiResponse.ok(_request_out(req))


# ── Leave balance ─────────────────────────────────────────────────────────────

@router.get("/balance", response_model=ApiResponse[list[LeaveBalanceOut]])
async def my_balance(
    year: int = Query(default=None, ge=2020, le=2100),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("leave:read")),
):
    """Return the calling employee's own leave balance."""
    from datetime import datetime
    effective_year = year or datetime.now().year
    balances = await leave_service.get_balances(db, current_user.id, effective_year)
    return ApiResponse.ok([_balance_out(b) for b in balances])


@router.get(
    "/balance/{employee_id}",
    response_model=ApiResponse[list[LeaveBalanceOut]],
)
async def employee_balance(
    employee_id: uuid.UUID,
    year: int = Query(default=None, ge=2020, le=2100),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:read")),
):
    """HR view: return any employee's leave balance."""
    from datetime import datetime
    effective_year = year or datetime.now().year
    balances = await leave_service.get_balances(db, employee_id, effective_year)
    return ApiResponse.ok([_balance_out(b) for b in balances])


@router.post(
    "/balance/adjust",
    response_model=ApiResponse[LeaveBalanceOut],
    status_code=201,
)
async def adjust_balance(
    body: LeaveBalanceAdjustIn,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("leave:write")),
):
    """HR manually sets allocated/carried-forward days for an employee."""
    balance = await leave_service.adjust_balance(db, body)
    # Reload with leave_type relationship
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(LeaveBalance)
        .where(LeaveBalance.id == balance.id)
        .options(selectinload(LeaveBalance.leave_type))
    )
    balance = result.scalar_one()
    return ApiResponse.ok(_balance_out(balance))
