"""Department CRUD service."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.branch import Branch, Department
from app.models.employee import Employee
from app.schemas.common import PaginationMeta
from app.schemas.departments import DepartmentCreate, DepartmentUpdate
from app.utils.pagination import paginate

_EAGER = [
    selectinload(Department.branch),
    selectinload(Department.head_employee),
]


async def _get_or_404(db: AsyncSession, dept_id: uuid.UUID) -> Department:
    result = await db.execute(
        select(Department)
        .where(Department.id == dept_id, Department.deleted_at.is_(None))
        .options(*_EAGER)
    )
    dept = result.scalar_one_or_none()
    if not dept:
        raise NotFoundError(f"Department {dept_id} not found")
    return dept


async def _employee_count(db: AsyncSession, dept_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Employee.id)).where(
            Employee.department_id == dept_id,
            Employee.deleted_at.is_(None),
        )
    )
    return result.scalar_one()


async def list_departments(
    db: AsyncSession,
    branch_id: uuid.UUID | None = None,
    per_page: int = 20,
    cursor: str | None = None,
) -> tuple[list[Department], PaginationMeta]:
    stmt = (
        select(Department)
        .where(Department.deleted_at.is_(None))
        .options(*_EAGER)
    )
    if branch_id:
        stmt = stmt.where(Department.branch_id == branch_id)
    return await paginate(db, stmt, Department, per_page, cursor)


async def get_department(db: AsyncSession, dept_id: uuid.UUID) -> Department:
    return await _get_or_404(db, dept_id)


async def create_department(
    db: AsyncSession, data: DepartmentCreate
) -> Department:
    # Validate branch exists
    branch = await db.execute(
        select(Branch.id).where(
            Branch.id == data.branch_id, Branch.deleted_at.is_(None)
        )
    )
    if not branch.scalar_one_or_none():
        raise NotFoundError(f"Branch {data.branch_id} not found")

    dept = Department(
        name=data.name,
        branch_id=data.branch_id,
        head_employee_id=data.head_employee_id,
    )
    db.add(dept)
    await db.flush()
    return await _get_or_404(db, dept.id)


async def update_department(
    db: AsyncSession, dept_id: uuid.UUID, data: DepartmentUpdate
) -> Department:
    dept = await _get_or_404(db, dept_id)
    updates = data.model_dump(exclude_unset=True)

    if "branch_id" in updates:
        branch = await db.execute(
            select(Branch.id).where(
                Branch.id == updates["branch_id"], Branch.deleted_at.is_(None)
            )
        )
        if not branch.scalar_one_or_none():
            raise NotFoundError(f"Branch {updates['branch_id']} not found")

    for field, value in updates.items():
        setattr(dept, field, value)

    await db.flush()
    return await _get_or_404(db, dept_id)


async def delete_department(db: AsyncSession, dept_id: uuid.UUID) -> None:
    dept = await _get_or_404(db, dept_id)
    count = await _employee_count(db, dept_id)
    if count > 0:
        raise UnprocessableError(
            f"Cannot delete department: {count} active employee(s) assigned"
        )
    dept.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def get_employee_count(db: AsyncSession, dept_id: uuid.UUID) -> int:
    return await _employee_count(db, dept_id)
