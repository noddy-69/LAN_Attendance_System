"""Branch CRUD and holiday sub-resource service."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.branch import Branch
from app.models.employee import Employee
from app.models.system import HolidayCalendar
from app.schemas.branches import BranchCreate, BranchUpdate, HolidayCreate
from app.schemas.common import PaginationMeta
from app.utils.pagination import paginate


async def _get_or_404(db: AsyncSession, branch_id: uuid.UUID) -> Branch:
    result = await db.execute(
        select(Branch).where(
            Branch.id == branch_id, Branch.deleted_at.is_(None)
        )
    )
    branch = result.scalar_one_or_none()
    if not branch:
        raise NotFoundError(f"Branch {branch_id} not found")
    return branch


async def _employee_count(db: AsyncSession, branch_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Employee.id)).where(
            Employee.branch_id == branch_id,
            Employee.deleted_at.is_(None),
        )
    )
    return result.scalar_one()


async def list_branches(
    db: AsyncSession,
    per_page: int = 20,
    cursor: str | None = None,
) -> tuple[list[Branch], PaginationMeta]:
    stmt = select(Branch).where(Branch.deleted_at.is_(None))
    return await paginate(db, stmt, Branch, per_page, cursor)


async def get_branch(db: AsyncSession, branch_id: uuid.UUID) -> Branch:
    return await _get_or_404(db, branch_id)


async def create_branch(db: AsyncSession, data: BranchCreate) -> Branch:
    branch = Branch(**data.model_dump())
    db.add(branch)
    await db.flush()
    await db.refresh(branch)
    return branch


async def update_branch(
    db: AsyncSession, branch_id: uuid.UUID, data: BranchUpdate
) -> Branch:
    branch = await _get_or_404(db, branch_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(branch, field, value)
    await db.flush()
    # Re-query so the response includes the DB-generated updated_at value.
    # (onupdate=func.now() marks the column expired after flush — accessing it
    # without a refresh triggers a lazy-load which fails in async context.)
    return await _get_or_404(db, branch_id)


async def delete_branch(db: AsyncSession, branch_id: uuid.UUID) -> None:
    branch = await _get_or_404(db, branch_id)
    count = await _employee_count(db, branch_id)
    if count > 0:
        from app.core.exceptions import UnprocessableError
        raise UnprocessableError(
            f"Cannot delete branch: {count} active employee(s) assigned"
        )
    branch.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def get_employee_count(db: AsyncSession, branch_id: uuid.UUID) -> int:
    return await _employee_count(db, branch_id)


# ── Holidays sub-resource ─────────────────────────────────────────────────────

async def list_holidays(
    db: AsyncSession,
    branch_id: uuid.UUID,
    year: int | None = None,
) -> list[HolidayCalendar]:
    await _get_or_404(db, branch_id)
    stmt = select(HolidayCalendar).where(
        HolidayCalendar.branch_id == branch_id,
        HolidayCalendar.deleted_at.is_(None),
    )
    if year:
        stmt = stmt.where(HolidayCalendar.year == year)
    stmt = stmt.order_by(HolidayCalendar.date)
    return list((await db.execute(stmt)).scalars().all())


async def create_holiday(
    db: AsyncSession, branch_id: uuid.UUID, data: HolidayCreate
) -> HolidayCalendar:
    await _get_or_404(db, branch_id)

    dup = await db.execute(
        select(HolidayCalendar.id).where(
            HolidayCalendar.date == data.date,
            HolidayCalendar.branch_id == branch_id,
            HolidayCalendar.deleted_at.is_(None),
        )
    )
    if dup.scalar_one_or_none():
        raise ConflictError("A holiday already exists on this date for this branch")

    holiday = HolidayCalendar(
        name=data.name,
        date=data.date,
        holiday_type=data.holiday_type,
        year=data.year,
        branch_id=branch_id,
    )
    db.add(holiday)
    await db.flush()
    await db.refresh(holiday)
    return holiday


async def delete_holiday(
    db: AsyncSession, branch_id: uuid.UUID, holiday_id: uuid.UUID
) -> None:
    result = await db.execute(
        select(HolidayCalendar).where(
            HolidayCalendar.id == holiday_id,
            HolidayCalendar.branch_id == branch_id,
            HolidayCalendar.deleted_at.is_(None),
        )
    )
    holiday = result.scalar_one_or_none()
    if not holiday:
        raise NotFoundError(f"Holiday {holiday_id} not found in branch {branch_id}")
    holiday.deleted_at = datetime.now(timezone.utc)
    await db.flush()
