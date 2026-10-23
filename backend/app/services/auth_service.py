import logging

import bcrypt as _bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.employee import Employee
from app.models.role import Role

log = logging.getLogger(__name__)

# Pre-computed at import time so bcrypt always runs during login even when
# the email doesn't exist.  This prevents timing-based user-enumeration:
# without it, a missing-email path returns in ~0ms vs ~100ms for wrong password.
_DUMMY_HASH: str = _bcrypt.hashpw(b"__sentinel__", _bcrypt.gensalt(rounds=12)).decode()


def _extract_permissions(employee: Employee) -> list[str]:
    if employee.role and employee.role.permissions:
        return [p.name for p in employee.role.permissions]
    return []


async def login(
    db: AsyncSession, email: str, password: str
) -> tuple[str, str, Employee]:
    """Authenticate by email + password.

    Always calls bcrypt regardless of whether the email exists so response
    timing cannot be used to enumerate valid accounts.

    Returns (access_token, refresh_token, employee).
    """
    result = await db.execute(
        select(Employee)
        .where(
            Employee.email == email,
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
        .options(selectinload(Employee.role).selectinload(Role.permissions))
    )
    employee = result.scalar_one_or_none()

    # Always run bcrypt — prevents timing oracle on email existence.
    candidate_hash = employee.password_hash if employee else _DUMMY_HASH
    password_ok = verify_password(password, candidate_hash)

    if not employee or not password_ok:
        raise UnauthorizedError("Invalid email or password")

    # License gate: when enforcing and the license is invalid/expired, only the
    # admin may log in (to view status and renew); everyone else is blocked.
    from app.core import license as _license
    if _license.blocks_non_admin():
        role_name = employee.role.name if employee.role else ""
        if role_name != "admin":
            raise UnauthorizedError(_license.get_status().get("message", "License invalid."))

    perms = _extract_permissions(employee)
    str_id = str(employee.id)
    return create_access_token(str_id, perms), create_refresh_token(str_id), employee


async def refresh(
    db: AsyncSession, refresh_token: str
) -> tuple[str, str, Employee]:
    """Validate a refresh token and issue a new access + refresh token pair."""
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid token type")

    result = await db.execute(
        select(Employee)
        .where(
            Employee.id == payload["sub"],
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
        .options(selectinload(Employee.role).selectinload(Role.permissions))
    )
    employee = result.scalar_one_or_none()
    if not employee:
        raise UnauthorizedError("User not found or inactive")

    perms = _extract_permissions(employee)
    str_id = str(employee.id)
    return create_access_token(str_id, perms), create_refresh_token(str_id), employee
