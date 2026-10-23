import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_permission
from app.models.employee import Employee
from app.schemas.branches import BranchCreate, BranchOut, BranchUpdate, HolidayCreate, HolidayOut
from app.schemas.common import ApiResponse
from app.services import branch_service

router = APIRouter(prefix="/branches", tags=["branches"])


async def _to_out(db: AsyncSession, branch) -> BranchOut:
    count = await branch_service.get_employee_count(db, branch.id)
    return BranchOut(
        id=branch.id,
        name=branch.name,
        address=branch.address,
        city=branch.city,
        state=branch.state,
        office_start_time=branch.office_start_time,
        office_end_time=branch.office_end_time,
        grace_period_minutes=branch.grace_period_minutes,
        employee_count=count,
        created_at=branch.created_at,
        updated_at=branch.updated_at,
    )


@router.get("", response_model=ApiResponse[list[BranchOut]])
async def list_branches(
    per_page: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:read")),
):
    branches, pagination = await branch_service.list_branches(
        db, per_page=per_page, cursor=cursor
    )
    items = [await _to_out(db, b) for b in branches]
    return ApiResponse.ok(items, pagination)


@router.post("", response_model=ApiResponse[BranchOut], status_code=201)
async def create_branch(
    body: BranchCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:write")),
):
    branch = await branch_service.create_branch(db, body)
    return ApiResponse.ok(await _to_out(db, branch))


@router.get("/{branch_id}", response_model=ApiResponse[BranchOut])
async def get_branch(
    branch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:read")),
):
    branch = await branch_service.get_branch(db, branch_id)
    return ApiResponse.ok(await _to_out(db, branch))


@router.patch("/{branch_id}", response_model=ApiResponse[BranchOut])
async def update_branch(
    branch_id: uuid.UUID,
    body: BranchUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:write")),
):
    branch = await branch_service.update_branch(db, branch_id, body)
    return ApiResponse.ok(await _to_out(db, branch))


@router.delete("/{branch_id}", response_model=ApiResponse[None])
async def delete_branch(
    branch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:write")),
):
    await branch_service.delete_branch(db, branch_id)
    return ApiResponse.ok(None)


# ── Holidays sub-resource ─────────────────────────────────────────────────────

@router.get("/{branch_id}/holidays", response_model=ApiResponse[list[HolidayOut]])
async def list_holidays(
    branch_id: uuid.UUID,
    year: int | None = Query(default=None, ge=2020, le=2100),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:read")),
):
    holidays = await branch_service.list_holidays(db, branch_id, year=year)
    return ApiResponse.ok(
        [
            HolidayOut(
                id=h.id,
                name=h.name,
                date=h.date,
                branch_id=h.branch_id,
                holiday_type=h.holiday_type,
                year=h.year,
                created_at=h.created_at,
            )
            for h in holidays
        ]
    )


@router.post(
    "/{branch_id}/holidays",
    response_model=ApiResponse[HolidayOut],
    status_code=201,
)
async def create_holiday(
    branch_id: uuid.UUID,
    body: HolidayCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:write")),
):
    holiday = await branch_service.create_holiday(db, branch_id, body)
    return ApiResponse.ok(
        HolidayOut(
            id=holiday.id,
            name=holiday.name,
            date=holiday.date,
            branch_id=holiday.branch_id,
            holiday_type=holiday.holiday_type,
            year=holiday.year,
            created_at=holiday.created_at,
        )
    )


@router.delete(
    "/{branch_id}/holidays/{holiday_id}",
    response_model=ApiResponse[None],
)
async def delete_holiday(
    branch_id: uuid.UUID,
    holiday_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:write")),
):
    await branch_service.delete_holiday(db, branch_id, holiday_id)
    return ApiResponse.ok(None)
