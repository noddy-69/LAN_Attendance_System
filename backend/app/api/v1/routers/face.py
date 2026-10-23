"""
Face router
===========
Endpoints:
  POST   /face/employees/{id}/enroll              — enroll a face photo
  DELETE /face/employees/{id}/embeddings/{emb_id} — delete one embedding
  GET    /face/employees/{id}/enrollment-status   — check enrollment
  GET    /face/embeddings/all                     — internal: all active embeddings
                                                    (called by face-recognition service)

Enrollment flow:
  1. Admin uploads a clear frontal face photo (JPEG/PNG/WEBP, max 10 MB)
  2. Backend POSTs the image to the face-recognition microservice at
     {FACE_SERVICE_URL}/embed which returns a 512-dim float vector
  3. Backend stores the vector in face_embeddings table via face_service.enroll()

The /embeddings/all endpoint is protected by X-Service-Key header
(value = SECRET_KEY env var) so the face-recognition service can fetch
all known embeddings at startup without needing a JWT.
"""
import asyncio
import json
import os
import urllib.error
import urllib.request
import uuid

from fastapi import APIRouter, Depends, File, Header, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError, UnprocessableError
from app.core.rbac import require_permission
from app.models.employee import Employee
from app.schemas.common import ApiResponse
from app.services import face_service

router = APIRouter(prefix="/face", tags=["face"])

_MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}

# Face-recognition microservice URL (Docker Compose internal service name)
_FACE_SERVICE_URL = os.environ.get("FACE_SERVICE_URL", "http://face-recognition:8001")

# Shared secret for the /embeddings/all internal endpoint
_FACE_SERVICE_KEY = os.environ.get("FACE_SERVICE_KEY", "")  # set via docker-compose env


# ── Schemas (inline) ──────────────────────────────────────────────────────────

from pydantic import BaseModel
from datetime import datetime


class FaceEmbeddingOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    model_version: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class EnrollmentStatusOut(BaseModel):
    employee_id: uuid.UUID
    is_enrolled: bool
    active_embedding_count: int
    total_embedding_count: int
    embeddings: list[FaceEmbeddingOut]


# ── Face service HTTP call ────────────────────────────────────────────────────

def _call_embed_sync(
    image_data: bytes,
    content_type: str,
) -> tuple[list[float], str]:
    """
    POST image bytes to the face-recognition service /embed endpoint.
    Returns (embedding_list, model_version).

    Expected response JSON:
      { "embedding": [float, ...], "model_version": "string" }
    """
    req = urllib.request.Request(
        f"{_FACE_SERVICE_URL}/embed",
        data=image_data,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
            return payload["embedding"], payload.get("model_version", "unknown")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise UnprocessableError(
            f"Face service returned {exc.code}: {body[:200]}"
        )
    except urllib.error.URLError as exc:
        raise UnprocessableError(
            f"Face service unavailable at {_FACE_SERVICE_URL}: {exc.reason}"
        )
    except (KeyError, json.JSONDecodeError) as exc:
        raise UnprocessableError(f"Unexpected face service response: {exc}")


async def _extract_embedding(
    image_data: bytes,
    content_type: str,
) -> tuple[list[float], str]:
    """Async wrapper — runs the blocking urllib call in a thread pool."""
    return await asyncio.to_thread(_call_embed_sync, image_data, content_type)


def _trigger_reload_sync() -> None:
    """Ask the face service to reload its embedding cache (best effort)."""
    try:
        req = urllib.request.Request(
            f"{_FACE_SERVICE_URL}/reload-embeddings", method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        # The cache also auto-refreshes every few minutes, so a failed nudge
        # is non-fatal — never let it break the enrollment response.
        pass


async def _trigger_face_reload() -> None:
    await asyncio.to_thread(_trigger_reload_sync)


# ── Serializers ───────────────────────────────────────────────────────────────

def _emb_out(e) -> FaceEmbeddingOut:
    return FaceEmbeddingOut(
        id=e.id,
        employee_id=e.employee_id,
        model_version=e.model_version,
        is_active=e.is_active,
        created_at=e.created_at,
    )


def _enrollment_out(status: dict) -> EnrollmentStatusOut:
    return EnrollmentStatusOut(
        employee_id=status["employee_id"],
        is_enrolled=status["is_enrolled"],
        active_embedding_count=status["active_embedding_count"],
        total_embedding_count=status["total_embedding_count"],
        embeddings=[_emb_out(e) for e in status["embeddings"]],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/employees/{employee_id}/enroll",
    response_model=ApiResponse[FaceEmbeddingOut],
    status_code=201,
)
async def enroll_face(
    employee_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("face:write")),
):
    """
    Enroll an employee's face.
    Upload a clear frontal photo (JPEG/PNG/WEBP, max 10 MB).
    The backend forwards it to the face-recognition service to extract
    a 512-dimensional embedding, then stores it in the database.
    """
    content_type = file.content_type or "image/jpeg"
    if content_type not in _ALLOWED_MIME:
        raise UnprocessableError(
            f"Unsupported image type '{content_type}'. "
            f"Allowed: {', '.join(sorted(_ALLOWED_MIME))}"
        )

    data = await file.read()
    if len(data) > _MAX_FILE_BYTES:
        raise UnprocessableError("Image too large — maximum size is 10 MB")
    if len(data) == 0:
        raise UnprocessableError("Uploaded file is empty")

    embedding, model_version = await _extract_embedding(data, content_type)

    fe = await face_service.enroll(
        db,
        employee_id=employee_id,
        embedding=embedding,
        model_version=model_version,
    )
    await db.commit()
    # Nudge the face service so the new face is recognised immediately.
    await _trigger_face_reload()
    return ApiResponse.ok(_emb_out(fe))


@router.delete(
    "/employees/{employee_id}/embeddings/{embedding_id}",
    response_model=ApiResponse[dict],
)
async def delete_embedding(
    employee_id: uuid.UUID,
    embedding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("face:write")),
):
    """Soft-delete a face embedding, then nudge the face service to reload."""
    await face_service.delete_embedding(db, embedding_id, employee_id)
    await db.commit()
    await _trigger_face_reload()
    return ApiResponse.ok({"deleted": str(embedding_id)})


@router.get(
    "/employees/{employee_id}/enrollment-status",
    response_model=ApiResponse[EnrollmentStatusOut],
)
async def enrollment_status(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("face:read")),
):
    """Check how many active face embeddings an employee has enrolled."""
    status = await face_service.get_enrollment_status(db, employee_id)
    return ApiResponse.ok(_enrollment_out(status))


@router.get("/policies")
async def face_policies(
    x_service_key: str = Header(alias="X-Service-Key", default=""),
    db: AsyncSession = Depends(get_db),
):
    """
    Internal endpoint — returns face-related system_policies for the face-recognition service.
    Auth: X-Service-Key header (same as /embeddings/all).
    Returns face.confidence_threshold and face.cooldown_seconds.
    """
    from app.core.config import settings as _cfg
    from sqlalchemy import select as _sel
    from app.models.system import SystemPolicy

    valid_key = _FACE_SERVICE_KEY or _cfg.SECRET_KEY
    if not x_service_key:
        raise UnauthorizedError("X-Service-Key header required")
    if x_service_key != valid_key:
        raise ForbiddenError("Invalid service key")

    result = await db.execute(
        _sel(SystemPolicy).where(
            SystemPolicy.key.like("face.%"),
            SystemPolicy.deleted_at.is_(None),
        )
    )
    policies = result.scalars().all()
    return {"policies": {p.key: p.value for p in policies}}


@router.get("/embeddings/all")
async def all_embeddings(
    x_service_key: str = Header(alias="X-Service-Key", default=""),
    db: AsyncSession = Depends(get_db),
):
    """
    Internal endpoint — called by the face-recognition microservice at startup
    and after any enrollment change to reload its in-memory embedding cache.

    Auth: X-Service-Key header must match FACE_SERVICE_KEY (or SECRET_KEY) env var.
    Not exposed through Nginx — accessible only on the internal Docker network.
    """
    from app.core.config import settings

    valid_key = _FACE_SERVICE_KEY or settings.SECRET_KEY
    if not x_service_key:
        raise UnauthorizedError("X-Service-Key header required")
    if x_service_key != valid_key:
        raise ForbiddenError("Invalid service key")

    embeddings = await face_service.get_all_active(db)
    payload = [
        {
            "id": str(e.id),
            "employee_id": str(e.employee_id),
            "embedding": e.embedding,          # list[float], 512 dims
            "model_version": e.model_version,
        }
        for e in embeddings
    ]
    return {"count": len(payload), "embeddings": payload}
