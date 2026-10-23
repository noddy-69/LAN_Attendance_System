"""
Audit helper — a single place to append immutable audit_logs rows.

Records who changed what (before → after) for compliance-relevant mutations across
the leave, reimbursement, attendance, employee and device workflows. Callers pass a
short dict for before/after (already JSON-serialisable values, e.g. strings/numbers).
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import AuditAction, AuditLog


async def record_audit(
    db: AsyncSession,
    *,
    table_name: str,
    record_id: uuid.UUID,
    action: AuditAction,
    performed_by_id: uuid.UUID | None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Append one audit_logs row and flush it (does not commit)."""
    db.add(
        AuditLog(
            table_name=table_name,
            record_id=record_id,
            action=action,
            before_value=before,
            after_value=after,
            performed_by_id=performed_by_id,
        )
    )
    await db.flush()
