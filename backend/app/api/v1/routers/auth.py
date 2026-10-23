from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import get_current_user
from app.schemas.auth import (
    EmployeeProfile,
    LoginRequest,
    TokenResponse,
)
from app.schemas.common import ApiResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "refresh_token"
_COOKIE_MAX_AGE = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # Derived from settings so HTTPS deployments get the Secure flag automatically.
        secure=settings.COOKIE_SECURE,
    )


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    access_token, refresh_token, _ = await auth_service.login(
        db, body.email, body.password
    )
    _set_refresh_cookie(response, refresh_token)
    return ApiResponse.ok(
        TokenResponse(
            access_token=access_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
    )


@router.post("/refresh", response_model=ApiResponse[TokenResponse])
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
):
    if not refresh_token:
        raise UnauthorizedError("No refresh token provided")
    new_access, new_refresh, _ = await auth_service.refresh(db, refresh_token)
    _set_refresh_cookie(response, new_refresh)
    return ApiResponse.ok(
        TokenResponse(
            access_token=new_access,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
    )


@router.post("/logout", response_model=ApiResponse[None])
async def logout(response: Response):
    response.delete_cookie(_COOKIE_NAME)
    return ApiResponse.ok(None)


@router.get("/me", response_model=ApiResponse[EmployeeProfile])
async def me(current_user=Depends(get_current_user)):
    perms: list[str] = getattr(current_user, "_permissions", [])
    return ApiResponse.ok(
        EmployeeProfile(
            id=current_user.id,
            employee_code=current_user.employee_code,
            first_name=current_user.first_name,
            last_name=current_user.last_name,
            email=current_user.email,
            phone=current_user.phone,
            role_name=current_user.role.name if current_user.role else "",
            branch_id=current_user.branch_id,
            branch_name=current_user.branch.name if current_user.branch else None,
            department_id=current_user.department_id,
            department_name=current_user.department.name if current_user.department else None,
            is_active=current_user.is_active,
            avatar_url=current_user.avatar_url,
            permissions=perms,
        )
    )
