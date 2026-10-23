import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import JWT_ALGORITHM, settings
from app.core.database import get_db

_bearer = HTTPBearer(auto_error=False)


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash with bcrypt cost-12. Returns a UTF-8 string safe to store in the DB."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time check; returns False (never raises) on any error."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _make_token(payload: dict[str, Any], expire_delta: timedelta) -> str:
    return jwt.encode(
        {**payload, "exp": datetime.now(timezone.utc) + expire_delta},
        settings.SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def create_access_token(employee_id: str, permissions: list[str]) -> str:
    return _make_token(
        {"sub": employee_id, "type": "access", "perms": permissions},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(employee_id: str) -> str:
    return _make_token(
        {"sub": employee_id, "type": "refresh"},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify signature + expiry. Raises UnauthorizedError on any failure."""
    from app.core.exceptions import UnauthorizedError

    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise UnauthorizedError("Invalid or expired token")


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    """
    Resolve Bearer token → active Employee ORM object.

    - Raises 401 for missing/invalid/expired tokens.
    - Raises 401 if the `sub` claim is not a valid UUID (malformed token).
    - Attaches `_permissions` from the token payload so callers never need
      an extra DB round-trip to check permissions.
    - Eagerly loads `role` so `employee.role.name` is always safe to access.
    """
    from app.core.exceptions import UnauthorizedError
    from app.models.employee import Employee
    from app.models.role import Role

    if not credentials:
        raise UnauthorizedError()

    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise UnauthorizedError("Wrong token type")

    # Validate UUID format before hitting the DB — a malformed `sub` claim
    # would otherwise cause an asyncpg error instead of a clean 401.
    try:
        employee_uuid = uuid.UUID(payload["sub"])
    except (ValueError, KeyError):
        raise UnauthorizedError("Invalid token subject")

    result = await db.execute(
        select(Employee)
        .where(
            Employee.id == employee_uuid,
            Employee.is_active.is_(True),
            Employee.deleted_at.is_(None),
        )
        .options(
            selectinload(Employee.role),
            selectinload(Employee.branch),
            selectinload(Employee.department),
        )
    )
    employee = result.scalar_one_or_none()
    if not employee:
        raise UnauthorizedError("User not found or inactive")

    # Non-column attribute — bypasses SQLAlchemy instrumentation safely.
    employee._permissions = payload.get("perms", [])
    return employee
