"""
Reimbursements router
=====================
Endpoints:
  POST   /reimbursements                          — employee submits claim
  POST   /reimbursements/{id}/receipts            — upload receipt to MinIO
  GET    /reimbursements                          — list claims (filtered)
  GET    /reimbursements/{id}                     — detail with presigned URLs
  PATCH  /reimbursements/{id}/manager-approve     — manager first approval
  PATCH  /reimbursements/{id}/manager-reject      — manager rejection
  PATCH  /reimbursements/{id}/hr-approve          — HR second approval
  PATCH  /reimbursements/{id}/hr-reject           — HR rejection
  PATCH  /reimbursements/{id}/mark-paid           — finance marks as paid

Monetary values: all amounts are INTEGER paise in requests, DB, and responses.
The frontend divides by 100 to display ₹.
"""
import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import UnprocessableError
from app.core.rbac import is_hr_tier, require_hr_tier_final_approval, require_permission
from app.core.scoping import assert_can_act_on, visible_employee_ids
from app.models.employee import Employee
from app.models.reimbursement import ReimbursementStatus
from app.schemas.common import ApiResponse
from app.schemas.reimbursements import (
    DocumentOut,
    ReimbursementActionIn,
    ReimbursementOut,
    ReimbursementSubmitIn,
)
from app.services import reimbursement_service, storage_service

router = APIRouter(prefix="/reimbursements", tags=["reimbursements"])

_MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB


# ── Serializers ───────────────────────────────────────────────────────────────

def _doc_out(doc, url: str | None = None) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        file_name=doc.file_name,
        url=url,
        file_size_bytes=doc.file_size_bytes,
        mime_type=doc.mime_type,
    )


def _claim_out(claim, documents: list[DocumentOut] | None = None) -> ReimbursementOut:
    """Sync serializer.  Pass pre-built documents list for detail views."""
    if documents is None:
        documents = [_doc_out(d) for d in (claim.documents or [])]
    return ReimbursementOut(
        id=claim.id,
        employee_id=claim.employee_id,
        employee_name=f"{claim.employee.first_name} {claim.employee.last_name}",
        title=claim.title,
        description=claim.description,
        amount_paise=claim.amount_paise,   # INTEGER paise — no conversion
        category=claim.category,
        expense_date=claim.expense_date,
        status=claim.status,
        manager_id=claim.manager_id,
        manager_name=(
            f"{claim.approving_manager.first_name} {claim.approving_manager.last_name}"
            if claim.approving_manager else None
        ),
        manager_action_at=claim.manager_action_at,
        manager_remarks=claim.manager_remarks,
        hr_id=claim.hr_id,
        hr_name=(
            f"{claim.approving_hr.first_name} {claim.approving_hr.last_name}"
            if claim.approving_hr else None
        ),
        hr_action_at=claim.hr_action_at,
        hr_remarks=claim.hr_remarks,
        paid_at=claim.paid_at,
        document_count=len(claim.documents or []),
        documents=documents,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


async def _claim_out_detail(claim) -> ReimbursementOut:
    """Detail view: generates 1-hour presigned MinIO URLs for each document."""
    documents = []
    for doc in (claim.documents or []):
        try:
            url = await storage_service.get_presigned_url(doc.file_path, expires_hours=1)
        except Exception:
            url = None
        documents.append(_doc_out(doc, url))
    return _claim_out(claim, documents)


# ── Permission helper ─────────────────────────────────────────────────────────

def _can_approve(current_user: Employee) -> bool:
    perms: list[str] = getattr(current_user, "_permissions", [])
    return "admin:*" in perms or "reimbursement:approve" in perms


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=ApiResponse[ReimbursementOut], status_code=201)
async def submit_claim(
    body: ReimbursementSubmitIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:read")),
):
    """
    Employee submits a reimbursement claim.
    amount_paise must be a positive integer (e.g. ₹500 → 50000).
    """
    claim = await reimbursement_service.submit(db, current_user.id, body)
    return ApiResponse.ok(_claim_out(claim))


@router.post(
    "/{reimbursement_id}/receipts",
    response_model=ApiResponse[DocumentOut],
    status_code=201,
)
async def upload_receipt(
    reimbursement_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:read")),
):
    """
    Upload a receipt image or PDF for an existing claim.
    Allowed MIME types: image/jpeg, image/png, image/webp, application/pdf.
    Max file size: 10 MB.
    """
    import os as _os
    data = await file.read()
    if len(data) > _MAX_FILE_BYTES:
        raise UnprocessableError("File too large — maximum size is 10 MB")

    slot_id = uuid.uuid4()
    content_type = file.content_type or "application/octet-stream"
    # Strip path components and null bytes from the filename — prevents path traversal in
    # both the MinIO object key and the file_name stored in the DB for display.
    raw_name = (file.filename or "receipt").replace("\x00", "")
    filename = _os.path.basename(raw_name) or "receipt"

    object_path = await storage_service.upload_receipt(
        reimbursement_id=reimbursement_id,
        slot_id=slot_id,
        filename=filename,
        data=data,
        content_type=content_type,
    )
    doc = await reimbursement_service.add_receipt(
        db,
        reimbursement_id=reimbursement_id,
        employee_id=current_user.id,
        file_name=filename,
        object_path=object_path,
        file_size_bytes=len(data),
        mime_type=content_type,
    )
    try:
        url = await storage_service.get_presigned_url(doc.file_path, expires_hours=1)
    except Exception:
        url = None

    return ApiResponse.ok(_doc_out(doc, url))


@router.delete("/{reimbursement_id}", response_model=ApiResponse[None])
async def delete_claim(
    reimbursement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:read")),
):
    """
    Delete a reimbursement claim that has not been approved yet.
    Employees may delete their own; HR/Admin may delete any pending claim.
    """
    await reimbursement_service.cancel_claim(
        db, reimbursement_id, current_user.id, is_privileged=is_hr_tier(current_user)
    )
    return ApiResponse.ok(None)


@router.get("", response_model=ApiResponse[list[ReimbursementOut]])
async def list_claims(
    employee_id: uuid.UUID | None = Query(default=None),
    status: ReimbursementStatus | None = Query(default=None),
    per_page: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:read")),
):
    """
    List reimbursement claims.
    Employees see only their own; managers see their department's employees; HR/Admin
    see all (and may filter by employee_id).
    """
    scope = await visible_employee_ids(db, current_user)
    claims, pagination = await reimbursement_service.list_claims(
        db,
        employee_id=(employee_id if scope is None else None),
        employee_ids=scope,
        status=status,
        per_page=per_page,
        cursor=cursor,
    )
    return ApiResponse.ok([_claim_out(c) for c in claims], pagination)


@router.get("/{reimbursement_id}", response_model=ApiResponse[ReimbursementOut])
async def get_claim(
    reimbursement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:read")),
):
    """
    Fetch a single claim with presigned MinIO URLs for all receipts.
    Employees can only view their own claim; HR/managers can view any.
    """
    claim = await reimbursement_service.get_claim(db, reimbursement_id)
    if not _can_approve(current_user) and claim.employee_id != current_user.id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("You do not have access to this reimbursement")
    return ApiResponse.ok(await _claim_out_detail(claim))


@router.patch(
    "/{reimbursement_id}/manager-approve",
    response_model=ApiResponse[ReimbursementOut],
)
async def manager_approve(
    reimbursement_id: uuid.UUID,
    body: ReimbursementActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:approve")),
):
    """Manager approves claim — moves status from PENDING_MANAGER → PENDING_HR."""
    existing = await reimbursement_service.get_claim(db, reimbursement_id)
    await assert_can_act_on(db, current_user, existing.employee_id)
    claim = await reimbursement_service.manager_approve(
        db, reimbursement_id, current_user.id, body.remarks
    )
    return ApiResponse.ok(_claim_out(claim))


@router.patch(
    "/{reimbursement_id}/manager-reject",
    response_model=ApiResponse[ReimbursementOut],
)
async def manager_reject(
    reimbursement_id: uuid.UUID,
    body: ReimbursementActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:approve")),
):
    """Manager rejects a claim at PENDING_MANAGER stage."""
    existing = await reimbursement_service.get_claim(db, reimbursement_id)
    await assert_can_act_on(db, current_user, existing.employee_id)
    claim = await reimbursement_service.reject(
        db, reimbursement_id, current_user.id, is_hr=False, remarks=body.remarks
    )
    return ApiResponse.ok(_claim_out(claim))


@router.patch(
    "/{reimbursement_id}/hr-approve",
    response_model=ApiResponse[ReimbursementOut],
)
async def hr_approve(
    reimbursement_id: uuid.UUID,
    body: ReimbursementActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:approve")),
):
    """HR/Admin final approval → APPROVED. May approve a claim still at the manager stage."""
    require_hr_tier_final_approval(current_user)
    claim = await reimbursement_service.hr_approve(
        db, reimbursement_id, current_user.id, body.remarks
    )
    return ApiResponse.ok(_claim_out(claim))


@router.patch(
    "/{reimbursement_id}/hr-reject",
    response_model=ApiResponse[ReimbursementOut],
)
async def hr_reject(
    reimbursement_id: uuid.UUID,
    body: ReimbursementActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:approve")),
):
    """HR rejects a claim at PENDING_HR stage."""
    claim = await reimbursement_service.reject(
        db, reimbursement_id, current_user.id, is_hr=True, remarks=body.remarks
    )
    return ApiResponse.ok(_claim_out(claim))


@router.patch(
    "/{reimbursement_id}/mark-paid",
    response_model=ApiResponse[ReimbursementOut],
)
async def mark_paid(
    reimbursement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("reimbursement:approve")),
):
    """Finance marks an APPROVED claim as PAID and records paid_at timestamp."""
    claim = await reimbursement_service.mark_paid(db, reimbursement_id, current_user.id)
    return ApiResponse.ok(_claim_out(claim))
