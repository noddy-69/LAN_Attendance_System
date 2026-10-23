from fastapi import Depends

from app.core.exceptions import ForbiddenError
from app.core.security import get_current_user


def require_permission(permission: str):
    """
    Dependency factory. Usage:

        @router.get("/...", dependencies=[Depends(require_permission("leave:approve"))])

    or inject and use the returned user:

        @router.get("/...")
        async def endpoint(user = Depends(require_permission("leave:approve"))):
    """
    async def _check(current_user=Depends(get_current_user)):
        perms: list[str] = getattr(current_user, "_permissions", [])
        if "admin:*" not in perms and permission not in perms:
            raise ForbiddenError(f"Missing permission: {permission}")
        return current_user

    return _check


def is_hr_tier(current_user) -> bool:
    """
    True for HR-or-above (HR, Admin) — i.e. the roles allowed to give FINAL approval
    and thereby directly finalize an item still pending a lower (manager) step.
    Managers hold *:approve but not employees:write, so they cannot self-finalize.
    """
    perms: list[str] = getattr(current_user, "_permissions", [])
    return "admin:*" in perms or "employees:write" in perms


def require_hr_tier_final_approval(current_user) -> None:
    """Raise unless the caller is HR/Admin. Guards the hr-approve (finalize) endpoints."""
    if not is_hr_tier(current_user):
        raise ForbiddenError(
            "Only HR or Admin can give final approval. "
            "Managers approve their step via the manager-approve action."
        )
