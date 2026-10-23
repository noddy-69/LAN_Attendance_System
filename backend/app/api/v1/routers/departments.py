import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_permission
from app.models.branch import Department
from app.models.employee import Employee
from app.schemas.common import ApiResponse
from app.schemas.departments import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services import department_service

router = APIRouter(prefix="/departments", tags=["departments"])


async def _to_out(db: AsyncSession, dept: Department) -> DepartmentOut:
    count = await department_service.get_employee_count(db, dept.id)
    head_name = None
    if dept.head_employee:
        head_name = f"{dept.head_employee.first_name} {dept.head_employee.last_name}"
    return DepartmentOut(
        id=dept.id,
        name=dept.name,
        branch_id=dept.branch_id,
        branch_name=dept.branch.name if dept.branch else "",
        head_employee_id=dept.head_employee_id,
        head_employee_name=head_name,
        employee_count=count,
        created_at=dept.created_at,
        updated_at=dept.updated_at,
    )


@router.get("", response_model=ApiResponse[list[DepartmentOut]])
async def list_departments(
    branch_id: uuid.UUID | None = Query(default=None),
    per_page: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("employees:read")),
):
    depts, pagination = await department_service.list_departments(
        db, branch_id=branch_id, per_page=per_page, cursor=cursor
    )
    items = [await _to_out(db, d) for d in depts]
    return ApiResponse.ok(items, pagination)


@router.post("", response_model=ApiResponse[DepartmentOut], status_code=201)
async def create_department(
    body: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("employees:write")),
):
    dept = await department_service.create_department(db, body)
    return ApiResponse.ok(await _to_out(db, dept))


@router.get("/{dept_id}", response_model=ApiResponse[DepartmentOut])
async def get_department(
    dept_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("employees:read")),
):
    dept = await department_service.get_department(db, dept_id)
    return ApiResponse.ok(await _to_out(db, dept))


@router.patch("/{dept_id}", response_model=ApiResponse[DepartmentOut])
async def update_department(
    dept_id: uuid.UUID,
    body: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("employees:write")),
):
    dept = await department_service.update_department(db, dept_id, body)
    return ApiResponse.ok(await _to_out(db, dept))


@router.delete("/{dept_id}", response_model=ApiResponse[None])
async def delete_department(
    dept_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("employees:write")),
):
    await department_service.delete_department(db, dept_id)
    return ApiResponse.ok(None)
