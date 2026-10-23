"""
Manager department-scoping.

A manager tracks only the employees in their OWN department (attendance, leave,
reimbursements, corrections). Admin/HR are unrestricted; a plain employee sees only
their own records.

The three-way result of ``visible_employee_ids``:
  • None    → unrestricted (Admin / HR)
  • [ids…]  → a manager's department members (empty if the manager has no department)
  • [self]  → a plain employee
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.models.employee import Employee
from app.models.role import Role


def _perms(user) -> list[str]:
    return getattr(user, "_permissions", [])


def can_see_all(user) -> bool:
    """Admin/HR — company-wide visibility (holds admin:* or employees:read)."""
    p = _perms(user)
    return "admin:*" in p or "employees:read" in p


def is_manager(user) -> bool:
    """A manager: can approve leave/reimbursement but is not Admin/HR."""
    p = _perms(user)
    return (("leave:approve" in p) or ("reimbursement:approve" in p)) and not can_see_all(user)


async def department_employee_ids(
    db: AsyncSession, department_id: uuid.UUID | None
) -> list[uuid.UUID]:
    """Active 'employee'-role members of a department — the people a manager tracks."""
    if department_id is None:
        return []
    res = await db.execute(
        select(Employee.id).where(
            Employee.department_id == department_id,
            Employee.deleted_at.is_(None),
            Employee.role.has(Role.name == "employee"),
        )
    )
    return [row[0] for row in res.all()]


async def visible_employee_ids(db: AsyncSession, user) -> list[uuid.UUID] | None:
    """Employee ids the user may view/act on. None = unrestricted (Admin/HR)."""
    if can_see_all(user):
        return None
    if is_manager(user):
        # Department members + the manager's own records (their own submissions).
        ids = await department_employee_ids(db, user.department_id)
        if user.id not in ids:
            ids.append(user.id)
        return ids
    return [user.id]


async def assert_can_act_on(db: AsyncSession, user, target_employee_id: uuid.UUID) -> None:
    """Raise ForbiddenError if `user` may not act on `target_employee_id`.

    No-op for Admin/HR. For a manager, the target must be in their department.
    """
    scope = await visible_employee_ids(db, user)
    if scope is None:
        return
    if target_employee_id not in scope:
        raise ForbiddenError(
            "You can only act on employees in your own department."
        )
