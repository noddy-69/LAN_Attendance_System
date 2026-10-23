"""Cursor-based pagination helpers shared by all list endpoints."""
import base64
import json
import uuid
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import PaginationMeta

T = TypeVar("T")


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    """Pack (created_at, id) → URL-safe base64 string."""
    return (
        base64.urlsafe_b64encode(
            json.dumps({"ca": created_at.isoformat(), "id": str(row_id)}).encode()
        )
        .rstrip(b"=")
        .decode()
    )


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Unpack cursor string → (created_at, id). Raises 422 on any parse failure."""
    from app.core.exceptions import UnprocessableError

    try:
        padded = cursor + "==" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(payload["ca"]), uuid.UUID(payload["id"])
    except Exception as exc:
        raise UnprocessableError("Invalid pagination cursor") from exc


async def paginate(
    db: AsyncSession,
    base_stmt: Any,  # Select without order_by / limit
    model_cls: Any,  # ORM class with .created_at and .id
    per_page: int,
    cursor: str | None,
) -> tuple[list, PaginationMeta]:
    """
    Apply cursor pagination to a SQLAlchemy select statement.

    - `base_stmt` must include all WHERE filters but no ORDER BY or LIMIT.
    - Returns (items, PaginationMeta).
    - Total count is the number of rows matching all filters (cursor-independent).
    """
    # ── Total count (filter-aware, cursor-independent) ─────────────────
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    # ── Apply cursor ───────────────────────────────────────────────────
    stmt = base_stmt
    if cursor:
        ca, cid = decode_cursor(cursor)
        stmt = stmt.where(
            tuple_(model_cls.created_at, model_cls.id) > tuple_(ca, cid)
        )

    stmt = stmt.order_by(model_cls.created_at, model_cls.id).limit(per_page + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    has_next = len(rows) > per_page
    items = rows[:per_page]

    next_cursor: str | None = None
    if has_next and items:
        last = items[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    return items, PaginationMeta(
        total=total,
        page=1,  # page number is meaningless in cursor pagination; always 1
        per_page=per_page,
        has_next=has_next,
        next_cursor=next_cursor,
    )
