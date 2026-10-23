import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_permission
from app.models.employee import Employee
from app.models.role import Role
from app.schemas.common import ApiResponse
from app.schemas.roles import PermissionOut, RoleCreate, RoleOut, RoleUpdate
from app.services import role_service

router = APIRouter(prefix="/roles", tags=["roles"])


async def _to_out(db: AsyncSession, role: Role) -> RoleOut:
    count = await role_service._employee_count(db, role.id)
    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=[
            PermissionOut(id=p.id, name=p.name, description=p.description)
            for p in role.permissions
        ],
        employee_count=count,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@router.get("", response_model=ApiResponse[list[RoleOut]])
async def list_roles(
    per_page: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("roles:read")),
):
    roles, pagination = await role_service.list_roles(db, per_page=per_page, cursor=cursor)
    items = [await _to_out(db, r) for r in roles]
    return ApiResponse.ok(items, pagination)


@router.get("/permissions", response_model=ApiResponse[list[PermissionOut]])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("roles:read")),
):
    perms = await role_service.list_permissions(db)
    return ApiResponse.ok(
        [PermissionOut(id=p.id, name=p.name, description=p.description) for p in perms]
    )


@router.post("", response_model=ApiResponse[RoleOut], status_code=201)
async def create_role(
    body: RoleCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("roles:write")),
):
    role = await role_service.create_role(db, body)
    return ApiResponse.ok(await _to_out(db, role))


@router.get("/{role_id}", response_model=ApiResponse[RoleOut])
async def get_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("roles:read")),
):
    role = await role_service.get_role(db, role_id)
    return ApiResponse.ok(await _to_out(db, role))


@router.patch("/{role_id}", response_model=ApiResponse[RoleOut])
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("roles:write")),
):
    role = await role_service.update_role(db, role_id, body)
    return ApiResponse.ok(await _to_out(db, role))


@router.delete("/{role_id}", response_model=ApiResponse[None])
async def delete_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("roles:write")),
):
    await role_service.delete_role(db, role_id)
    return ApiResponse.ok(None)
