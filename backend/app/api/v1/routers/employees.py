import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_permission
from app.core.security import get_current_user
from app.models.employee import Employee
from app.schemas.common import ApiResponse
from app.schemas.employees import (
    DirectReportOut,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    HierarchyNodeOut,
)
from app.services import employee_service, storage_service

router = APIRouter(prefix="/employees", tags=["employees"])

_MAX_AVATAR = 5 * 1024 * 1024  # 5 MB


def _to_out(emp: Employee) -> EmployeeOut:
    return EmployeeOut(
        id=emp.id,
        employee_code=emp.employee_code,
        first_name=emp.first_name,
        last_name=emp.last_name,
        email=emp.email,
        phone=emp.phone,
        role_id=emp.role_id,
        role_name=emp.role.name if emp.role else "",
        branch_id=emp.branch_id,
        branch_name=emp.branch.name if emp.branch else "",
        department_id=emp.department_id,
        department_name=emp.department.name if emp.department else None,
        shift_id=emp.shift_id,
        manager_id=emp.manager_id,
        manager_name=(
            f"{emp.manager.first_name} {emp.manager.last_name}"
            if emp.manager
            else None
        ),
        biometric_uid=emp.biometric_uid,
        date_of_joining=emp.date_of_joining,
        date_of_leaving=emp.date_of_leaving,
        is_active=emp.is_active,
        monthly_salary_paise=emp.monthly_salary_paise,
        avatar_url=emp.avatar_url,
        created_at=emp.created_at,
        updated_at=emp.updated_at,
    )


@router.get("", response_model=ApiResponse[list[EmployeeOut]])
async def list_employees(
    branch_id: uuid.UUID | None = Query(default=None),
    department_id: uuid.UUID | None = Query(default=None),
    role_id: uuid.UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    per_page: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("employees:read")),
):
    employees, pagination = await employee_service.list_employees(
        db,
        branch_id=branch_id,
        department_id=department_id,
        role_id=role_id,
        is_active=is_active,
        search=search,
        per_page=per_page,
        cursor=cursor,
    )
    return ApiResponse.ok([_to_out(e) for e in employees], pagination)


@router.post("", response_model=ApiResponse[EmployeeOut], status_code=201)
async def create_employee(
    body: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("employees:write")),
):
    emp = await employee_service.create_employee(db, body, actor_id=current_user.id)
    return ApiResponse.ok(_to_out(emp))


@router.get("/{employee_id}", response_model=ApiResponse[EmployeeOut])
async def get_employee(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("employees:read")),
):
    emp = await employee_service.get_employee(db, employee_id)
    return ApiResponse.ok(_to_out(emp))


@router.patch("/{employee_id}", response_model=ApiResponse[EmployeeOut])
async def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    from app.core.exceptions import ForbiddenError

    perms = getattr(current_user, "_permissions", [])
    if "admin:*" not in perms and "employees:write" not in perms:
        # Self-service: a user may edit only their OWN profile, and only safe fields
        # (name, phone) — never role / branch / department / biometric_uid.
        if employee_id != current_user.id:
            raise ForbiddenError("You can only edit your own profile.")
        allowed = {"first_name", "last_name", "phone"}
        provided = body.model_dump(exclude_unset=True)
        body = EmployeeUpdate(**{k: v for k, v in provided.items() if k in allowed})

    emp = await employee_service.update_employee(db, employee_id, body, actor_id=current_user.id)
    return ApiResponse.ok(_to_out(emp))


@router.delete("/{employee_id}", response_model=ApiResponse[None])
async def delete_employee(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("employees:write")),
):
    await employee_service.delete_employee(db, employee_id, actor_id=current_user.id)
    return ApiResponse.ok(None)


@router.post("/{employee_id}/avatar", response_model=ApiResponse[EmployeeOut])
async def upload_avatar(
    employee_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    from app.core.exceptions import ForbiddenError, UnprocessableError

    # A user may set their OWN profile photo; changing someone else's needs employees:write.
    perms = getattr(current_user, "_permissions", [])
    if (
        employee_id != current_user.id
        and "admin:*" not in perms
        and "employees:write" not in perms
    ):
        raise ForbiddenError("You can only change your own profile photo.")

    if file.content_type not in storage_service.AVATAR_MIME_TYPES:
        raise UnprocessableError(
            f"Unsupported type. Allowed: {', '.join(storage_service.AVATAR_MIME_TYPES)}"
        )
    data = await file.read()
    if len(data) > _MAX_AVATAR:
        raise UnprocessableError("Avatar must be ≤ 5 MB")

    avatar_url = await storage_service.upload_avatar(employee_id, data, file.content_type)
    emp = await employee_service.update_avatar(db, employee_id, avatar_url)
    return ApiResponse.ok(_to_out(emp))


@router.get(
    "/{employee_id}/direct-reports",
    response_model=ApiResponse[list[DirectReportOut]],
)
async def get_direct_reports(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("attendance:read")),
):
    from app.core.exceptions import ForbiddenError
    from app.core.scoping import can_see_all
    # A manager may only view their OWN department team; HR/Admin may view anyone's.
    if not can_see_all(current_user) and employee_id != current_user.id:
        raise ForbiddenError("You can only view your own team.")
    reports = await employee_service.get_direct_reports(db, employee_id)
    return ApiResponse.ok(
        [
            DirectReportOut(
                id=r.id,
                employee_code=r.employee_code,
                first_name=r.first_name,
                last_name=r.last_name,
                email=r.email,
                role_name=r.role.name if r.role else "",
                is_active=r.is_active,
            )
            for r in reports
        ]
    )


@router.get(
    "/{employee_id}/hierarchy",
    response_model=ApiResponse[list[HierarchyNodeOut]],
)
async def get_hierarchy(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("employees:read")),
):
    chain = await employee_service.get_hierarchy(db, employee_id)
    return ApiResponse.ok(chain)
