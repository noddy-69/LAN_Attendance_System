from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationMeta(BaseModel):
    total: int
    page: int
    per_page: int
    has_next: bool
    next_cursor: str | None = None


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    error: str | None = None
    message: str | None = None
    pagination: PaginationMeta | None = None

    @classmethod
    def ok(
        cls,
        data: T,
        pagination: PaginationMeta | None = None,
        message: str | None = None,
    ) -> "ApiResponse[T]":
        return cls(success=True, data=data, pagination=pagination, message=message)

    @classmethod
    def fail(cls, error: str) -> "ApiResponse[None]":
        return cls(success=False, error=error)
