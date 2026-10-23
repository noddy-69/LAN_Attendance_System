"""
Reimbursement Service
=====================

Approval flow:
    Employee submits → PENDING_MANAGER
    Manager approves → PENDING_HR
    HR approves      → APPROVED
    Finance marks    → PAID
    Manager/HR rejects at any step → REJECTED

All monetary amounts are INTEGER paise.  This service never converts to/from
rupees — that is strictly a frontend concern.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.reimbursement import Reimbursement, ReimbursementDocument, ReimbursementStatus
from app.models.system import AuditAction
from app.services.audit_service import record_audit
from app.schemas.common import PaginationMeta
from app.schemas.reimbursements import ReimbursementSubmitIn
from app.utils.pagination import paginate

_NOW = lambda: datetime.now(timezone.utc)

_EAGER = [
    selectinload(Reimbursement.employee),
    selectinload(Reimbursement.approving_manager),
    selectinload(Reimbursement.approving_hr),
    selectinload(Reimbursement.documents),
]


async def _get_or_404(db: AsyncSession, reimbursement_id: uuid.UUID) -> Reimbursement:
    result = await db.execute(
        select(Reimbursement)
        .where(
            Reimbursement.id == reimbursement_id,
            Reimbursement.deleted_at.is_(None),
        )
        .options(*_EAGER)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise NotFoundError(f"Reimbursement {reimbursement_id} not found")
    return r


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def submit(
    db: AsyncSession,
    employee_id: uuid.UUID,
    data: ReimbursementSubmitIn,
) -> Reimbursement:
    """
    Employee submits a claim.  amount_paise is stored as-is (integer paise).
    The service never touches rupee values.
    """
    claim = Reimbursement(
        employee_id=employee_id,
        title=data.title,
        description=data.description,
        amount_paise=data.amount_paise,   # INTEGER paise — no conversion
        category=data.category,
        expense_date=data.expense_date,
        status=ReimbursementStatus.PENDING_MANAGER,
    )
    db.add(claim)
    await db.flush()
    await record_audit(
        db, table_name="reimbursements", record_id=claim.id,
        action=AuditAction.CREATE, performed_by_id=employee_id,
        after={"title": claim.title, "amount_paise": claim.amount_paise,
               "category": claim.category.value if claim.category else None,
               "status": claim.status.value},
    )
    return await _get_or_404(db, claim.id)


async def add_receipt(
    db: AsyncSession,
    reimbursement_id: uuid.UUID,
    employee_id: uuid.UUID,
    file_name: str,
    object_path: str,
    file_size_bytes: int,
    mime_type: str,
) -> ReimbursementDocument:
    """
    Register a receipt document after it has been uploaded to MinIO.
    Only the owning employee (or HR) should call this.
    """
    claim = await _get_or_404(db, reimbursement_id)

    # Receipts can be added while the claim is still pending
    uploadable = {
        ReimbursementStatus.PENDING_MANAGER,
        ReimbursementStatus.PENDING_HR,
    }
    if claim.status not in uploadable:
        raise UnprocessableError(
            f"Cannot add receipt to a claim with status '{claim.status}'"
        )
    # Verify the submitter owns this claim (or is HR — ownership enforced by router)
    if claim.employee_id != employee_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Cannot upload receipt for another employee's claim")

    doc = ReimbursementDocument(
        reimbursement_id=reimbursement_id,
        file_name=file_name,
        file_path=object_path,
        file_size_bytes=file_size_bytes,
        mime_type=mime_type,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


async def manager_approve(
    db: AsyncSession,
    reimbursement_id: uuid.UUID,
    manager_id: uuid.UUID,
    remarks: str | None,
) -> Reimbursement:
    claim = await _get_or_404(db, reimbursement_id)
    if claim.status != ReimbursementStatus.PENDING_MANAGER:
        raise UnprocessableError(
            f"Claim is '{claim.status}', not pending manager approval"
        )
    prev = claim.status.value
    claim.status = ReimbursementStatus.PENDING_HR
    claim.manager_id = manager_id
    claim.manager_action_at = _NOW()
    claim.manager_remarks = remarks
    await db.flush()
    final = await _get_or_404(db, reimbursement_id)
    await record_audit(
        db, table_name="reimbursements", record_id=reimbursement_id,
        action=AuditAction.UPDATE, performed_by_id=manager_id,
        before={"status": prev}, after={"status": final.status.value},
    )

    from app.tasks.notifications import send_notification
    send_notification.delay(
        str(claim.employee_id), "REIMBURSEMENT_UPDATE",
        claim_title=claim.title, amount=round(claim.amount_paise / 100, 2),
        status="pending HR approval",
        reference_id=str(reimbursement_id), reference_type="reimbursements",
    )
    return final


async def hr_approve(
    db: AsyncSession,
    reimbursement_id: uuid.UUID,
    hr_id: uuid.UUID,
    remarks: str | None,
) -> Reimbursement:
    claim = await _get_or_404(db, reimbursement_id)
    # HR/Admin finalize: accept a claim still pending the manager's step too, so a
    # higher role can approve directly without waiting for the manager.
    if claim.status not in (ReimbursementStatus.PENDING_HR, ReimbursementStatus.PENDING_MANAGER):
        raise UnprocessableError(
            f"Claim is '{claim.status}', not awaiting approval"
        )
    prev = claim.status.value
    claim.status = ReimbursementStatus.APPROVED
    claim.hr_id = hr_id
    claim.hr_action_at = _NOW()
    claim.hr_remarks = remarks
    await db.flush()
    final = await _get_or_404(db, reimbursement_id)
    await record_audit(
        db, table_name="reimbursements", record_id=reimbursement_id,
        action=AuditAction.UPDATE, performed_by_id=hr_id,
        before={"status": prev}, after={"status": final.status.value},
    )

    from app.tasks.notifications import send_notification
    send_notification.delay(
        str(claim.employee_id), "REIMBURSEMENT_UPDATE",
        claim_title=claim.title, amount=round(claim.amount_paise / 100, 2),
        status="approved",
        reference_id=str(reimbursement_id), reference_type="reimbursements",
    )
    return final


async def reject(
    db: AsyncSession,
    reimbursement_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    is_hr: bool,
    remarks: str | None,
) -> Reimbursement:
    """Manager or HR rejects at any pending stage."""
    claim = await _get_or_404(db, reimbursement_id)
    rejectable = {ReimbursementStatus.PENDING_MANAGER, ReimbursementStatus.PENDING_HR}
    if claim.status not in rejectable:
        raise UnprocessableError(
            f"Cannot reject a claim with status '{claim.status}'"
        )
    if is_hr:
        claim.hr_id = actor_id
        claim.hr_action_at = _NOW()
        claim.hr_remarks = remarks
    else:
        claim.manager_id = actor_id
        claim.manager_action_at = _NOW()
        claim.manager_remarks = remarks
    prev = claim.status.value
    claim.status = ReimbursementStatus.REJECTED
    await db.flush()
    final = await _get_or_404(db, reimbursement_id)
    await record_audit(
        db, table_name="reimbursements", record_id=reimbursement_id,
        action=AuditAction.UPDATE, performed_by_id=actor_id,
        before={"status": prev}, after={"status": final.status.value},
    )

    from app.tasks.notifications import send_notification
    send_notification.delay(
        str(claim.employee_id), "REIMBURSEMENT_UPDATE",
        claim_title=claim.title, amount=round(claim.amount_paise / 100, 2),
        status="rejected",
        reference_id=str(reimbursement_id), reference_type="reimbursements",
    )
    return final


async def mark_paid(
    db: AsyncSession,
    reimbursement_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> Reimbursement:
    claim = await _get_or_404(db, reimbursement_id)
    if claim.status != ReimbursementStatus.APPROVED:
        raise UnprocessableError(
            f"Can only mark APPROVED claims as paid; current status is '{claim.status}'"
        )
    prev = claim.status.value
    claim.status = ReimbursementStatus.PAID
    claim.paid_at = _NOW()
    await db.flush()
    final = await _get_or_404(db, reimbursement_id)
    await record_audit(
        db, table_name="reimbursements", record_id=reimbursement_id,
        action=AuditAction.UPDATE, performed_by_id=actor_id,
        before={"status": prev}, after={"status": final.status.value},
    )

    from app.tasks.notifications import send_notification
    send_notification.delay(
        str(claim.employee_id), "REIMBURSEMENT_UPDATE",
        claim_title=claim.title, amount=round(claim.amount_paise / 100, 2),
        status="paid",
        reference_id=str(reimbursement_id), reference_type="reimbursements",
    )
    return final


async def cancel_claim(
    db: AsyncSession,
    reimbursement_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_privileged: bool,
) -> None:
    """
    Delete (soft) a reimbursement claim that has not been approved yet.
    Employees may delete only their own; HR/Admin may delete any pending claim.
    """
    claim = await _get_or_404(db, reimbursement_id)
    if not is_privileged and claim.employee_id != actor_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("You can only delete your own reimbursement claim")
    if claim.status not in (ReimbursementStatus.PENDING_MANAGER, ReimbursementStatus.PENDING_HR):
        raise UnprocessableError(
            f"Only a claim awaiting approval can be deleted; this one is '{claim.status.value}'"
        )
    prev = claim.status.value
    claim.deleted_at = _NOW()
    await db.flush()
    await record_audit(
        db, table_name="reimbursements", record_id=reimbursement_id,
        action=AuditAction.DELETE, performed_by_id=actor_id,
        before={"status": prev}, after={"deleted": True},
    )


# ── Query helpers ─────────────────────────────────────────────────────────────

async def list_claims(
    db: AsyncSession,
    *,
    employee_id: uuid.UUID | None = None,
    employee_ids: list[uuid.UUID] | None = None,
    status: ReimbursementStatus | None = None,
    per_page: int = 20,
    cursor: str | None = None,
) -> tuple[list[Reimbursement], PaginationMeta]:
    stmt = (
        select(Reimbursement)
        .where(Reimbursement.deleted_at.is_(None))
        .options(*_EAGER)
    )
    if employee_id:
        stmt = stmt.where(Reimbursement.employee_id == employee_id)
    # Restrict to a set of employees (e.g. a manager's department); [] yields no rows.
    if employee_ids is not None:
        stmt = stmt.where(Reimbursement.employee_id.in_(employee_ids))
    if status:
        stmt = stmt.where(Reimbursement.status == status)
    return await paginate(db, stmt, Reimbursement, per_page, cursor)


async def get_claim(db: AsyncSession, reimbursement_id: uuid.UUID) -> Reimbursement:
    return await _get_or_404(db, reimbursement_id)
