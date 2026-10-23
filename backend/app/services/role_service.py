"""Role and Permission CRUD service."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.employee import Employee
from app.models.role import Permission, Role
from app.schemas.common import PaginationMeta
from app.schemas.roles import RoleCreate, RoleUpdate
from app.utils.pagination import paginate


async def _get_role_or_404(db: AsyncSession, role_id: uuid.UUID) -> Role:
    result = await db.execute(
        select(Role)
        .where(Role.id == role_id, Role.deleted_at.is_(None))
        .options(selectinload(Role.permissions))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise NotFoundError(f"Role {role_id} not found")
    return role


async def _employee_count(db: AsyncSession, role_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Employee.id)).where(
            Employee.role_id == role_id,
            Employee.deleted_at.is_(None),
        )
    )
    return result.scalar_one()


async def list_roles(
    db: AsyncSession,
    per_page: int = 20,
    cursor: str | None = None,
) -> tuple[list[Role], PaginationMeta]:
    stmt = (
        select(Role)
        .where(Role.deleted_at.is_(None))
        .options(selectinload(Role.permissions))
    )
    return await paginate(db, stmt, Role, per_page, cursor)


async def get_role(db: AsyncSession, role_id: uuid.UUID) -> Role:
    return await _get_role_or_404(db, role_id)


async def create_role(db: AsyncSession, data: RoleCreate) -> Role:
    dup = await db.execute(
        select(Role.id).where(Role.name == data.name, Role.deleted_at.is_(None))
    )
    if dup.scalar_one_or_none():
        raise ConflictError(f"Role '{data.name}' already exists")

    perms = await _resolve_permissions(db, data.permission_ids)
    role = Role(name=data.name, description=data.description)
    role.permissions = perms
    db.add(role)
    await db.flush()
    return await _get_role_or_404(db, role.id)


async def update_role(
    db: AsyncSession, role_id: uuid.UUID, data: RoleUpdate
) -> Role:
    role = await _get_role_or_404(db, role_id)
    updates = data.model_dump(exclude_unset=True)

    if "name" in updates and updates["name"] != role.name:
        dup = await db.execute(
            select(Role.id).where(
                Role.name == updates["name"],
                Role.id != role_id,
                Role.deleted_at.is_(None),
            )
        )
        if dup.scalar_one_or_none():
            raise ConflictError(f"Role '{updates['name']}' already exists")
        role.name = updates["name"]

    if "description" in updates:
        role.description = updates["description"]

    if "permission_ids" in updates and updates["permission_ids"] is not None:
        role.permissions = await _resolve_permissions(db, updates["permission_ids"])

    await db.flush()
    return await _get_role_or_404(db, role_id)


async def delete_role(db: AsyncSession, role_id: uuid.UUID) -> None:
    role = await _get_role_or_404(db, role_id)
    count = await _employee_count(db, role_id)
    if count > 0:
        raise UnprocessableError(
            f"Cannot delete role: {count} active employee(s) assigned to it"
        )
    role.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def list_permissions(db: AsyncSession) -> list[Permission]:
    result = await db.execute(
        select(Permission)
        .where(Permission.deleted_at.is_(None))
        .order_by(Permission.name)
    )
    return list(result.scalars().all())


async def _resolve_permissions(
    db: AsyncSession, ids: list[uuid.UUID]
) -> list[Permission]:
    if not ids:
        return []
    result = await db.execute(
        select(Permission).where(Permission.id.in_(ids))
    )
    found = list(result.scalars().all())
    if len(found) != len(set(ids)):
        raise NotFoundError("One or more permission IDs do not exist")
    return found
