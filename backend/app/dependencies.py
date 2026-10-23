from dataclasses import dataclass

from fastapi import Query


@dataclass
class PaginationParams:
    """Standard cursor-based pagination params injected as a FastAPI dependency."""
    page: int
    per_page: int
    cursor: str | None


def pagination(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    cursor: str | None = Query(default=None, description="Opaque cursor for next page"),
) -> PaginationParams:
    return PaginationParams(page=page, per_page=per_page, cursor=cursor)
