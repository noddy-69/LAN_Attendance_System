import uuid
from datetime import time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.rbac import require_permission
from app.models.employee import Employee
from app.models.shift import ShiftDefinition
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/shifts", tags=["shifts"])


class ShiftCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    start_time: time
    end_time: time
    required_minutes: int = Field(ge=1, le=1440)
    is_overnight: bool = False
    branch_id: uuid.UUID | None = None


class ShiftUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    start_time: time | None = None
    end_time: time | None = None
    required_minutes: int | None = Field(default=None, ge=1, le=1440)
    is_overnight: bool | None = None
    branch_id: uuid.UUID | None = None


class ShiftOut(BaseModel):
    id: uuid.UUID
    name: str
    start_time: time
    end_time: time
    required_minutes: int
    is_overnight: bool
    branch_id: uuid.UUID | None

    class Config:
        from_attributes = True


@router.get("", response_model=ApiResponse[list[ShiftOut]])
async def list_shifts(
    branch_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:read")),
):
    stmt = select(ShiftDefinition).where(ShiftDefinition.deleted_at.is_(None))
    if branch_id:
        stmt = stmt.where(ShiftDefinition.branch_id == branch_id)
    stmt = stmt.order_by(ShiftDefinition.name)
    result = await db.execute(stmt)
    shifts = list(result.scalars().all())
    return ApiResponse.ok([ShiftOut.model_validate(s) for s in shifts])


@router.post("", response_model=ApiResponse[ShiftOut], status_code=201)
async def create_shift(
    body: ShiftCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("admin:*")),
):
    shift = ShiftDefinition(
        name=body.name,
        start_time=body.start_time,
        end_time=body.end_time,
        required_minutes=body.required_minutes,
        is_overnight=body.is_overnight,
        branch_id=body.branch_id,
    )
    db.add(shift)
    await db.flush()
    await db.refresh(shift)
    return ApiResponse.ok(ShiftOut.model_validate(shift))


@router.get("/{shift_id}", response_model=ApiResponse[ShiftOut])
async def get_shift(
    shift_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("branches:read")),
):
    result = await db.execute(
        select(ShiftDefinition).where(
            ShiftDefinition.id == shift_id,
            ShiftDefinition.deleted_at.is_(None),
        )
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise NotFoundError(f"Shift {shift_id} not found")
    return ApiResponse.ok(ShiftOut.model_validate(shift))


@router.patch("/{shift_id}", response_model=ApiResponse[ShiftOut])
async def update_shift(
    shift_id: uuid.UUID,
    body: ShiftUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("admin:*")),
):
    result = await db.execute(
        select(ShiftDefinition).where(
            ShiftDefinition.id == shift_id,
            ShiftDefinition.deleted_at.is_(None),
        )
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise NotFoundError(f"Shift {shift_id} not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(shift, field, value)
    await db.flush()
    await db.refresh(shift)
    return ApiResponse.ok(ShiftOut.model_validate(shift))


@router.delete("/{shift_id}", response_model=ApiResponse[None])
async def delete_shift(
    shift_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("admin:*")),
):
    from datetime import datetime, timezone
    result = await db.execute(
        select(ShiftDefinition).where(
            ShiftDefinition.id == shift_id,
            ShiftDefinition.deleted_at.is_(None),
        )
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise NotFoundError(f"Shift {shift_id} not found")
    shift.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return ApiResponse.ok(None)
