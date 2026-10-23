"""
Face Service
============
Manages face embeddings stored in face_embeddings table.

Enrollment flow (called by face.py router):
  1. Admin uploads a clear face photo via POST /face/employees/{id}/enroll
  2. Router calls the face-recognition microservice (face-service container)
     at FACE_SERVICE_URL/embed to extract the 512-dim embedding
  3. Router calls enroll() here to persist it

The face-recognition microservice calls GET /face/embeddings/all at startup
and periodically to load all active embeddings into memory for recognition.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ForbiddenError, NotFoundError, UnprocessableError
from app.models.employee import Employee
from app.models.face_embedding import FaceEmbedding

_NOW = lambda: datetime.now(timezone.utc)
_EXPECTED_DIM = 512


async def get_all_active(db: AsyncSession) -> list[FaceEmbedding]:
    """Return all active (non-deleted) embeddings — used by face service at startup."""
    result = await db.execute(
        select(FaceEmbedding).where(
            FaceEmbedding.is_active.is_(True),
            FaceEmbedding.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def enroll(
    db: AsyncSession,
    employee_id: uuid.UUID,
    embedding: list[float],
    model_version: str,
) -> FaceEmbedding:
    """Persist a new face embedding for an employee."""
    emp_check = await db.execute(
        select(Employee.id).where(
            Employee.id == employee_id,
            Employee.deleted_at.is_(None),
        )
    )
    if not emp_check.scalar_one_or_none():
        raise NotFoundError(f"Employee {employee_id} not found")

    if len(embedding) != _EXPECTED_DIM:
        raise UnprocessableError(
            f"Expected {_EXPECTED_DIM}-dimensional embedding, got {len(embedding)}"
        )

    fe = FaceEmbedding(
        employee_id=employee_id,
        embedding=embedding,
        model_version=model_version,
        is_active=True,
    )
    db.add(fe)
    await db.flush()
    await db.refresh(fe)
    return fe


async def delete_embedding(
    db: AsyncSession,
    embedding_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> None:
    """Soft-delete a face embedding and deactivate it."""
    result = await db.execute(
        select(FaceEmbedding).where(
            FaceEmbedding.id == embedding_id,
            FaceEmbedding.deleted_at.is_(None),
        )
    )
    fe = result.scalar_one_or_none()
    if not fe:
        raise NotFoundError(f"Face embedding {embedding_id} not found")
    if fe.employee_id != employee_id:
        raise ForbiddenError("Embedding does not belong to this employee")

    fe.is_active = False
    fe.deleted_at = _NOW()
    await db.flush()


async def get_embeddings_for_employee(
    db: AsyncSession,
    employee_id: uuid.UUID,
) -> list[FaceEmbedding]:
    result = await db.execute(
        select(FaceEmbedding).where(
            FaceEmbedding.employee_id == employee_id,
            FaceEmbedding.deleted_at.is_(None),
        ).order_by(FaceEmbedding.created_at.desc())
    )
    return list(result.scalars().all())


async def get_enrollment_status(
    db: AsyncSession,
    employee_id: uuid.UUID,
) -> dict:
    emp_check = await db.execute(
        select(Employee.id).where(
            Employee.id == employee_id,
            Employee.deleted_at.is_(None),
        )
    )
    if not emp_check.scalar_one_or_none():
        raise NotFoundError(f"Employee {employee_id} not found")

    embeddings = await get_embeddings_for_employee(db, employee_id)
    active = [e for e in embeddings if e.is_active]
    return {
        "employee_id": employee_id,
        "is_enrolled": len(active) > 0,
        "active_embedding_count": len(active),
        "total_embedding_count": len(embeddings),
        "embeddings": active,
    }
