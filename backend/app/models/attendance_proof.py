import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProofType(str, enum.Enum):
    ENTRY_IMAGE = "entry_image"
    EXIT_IMAGE = "exit_image"


class AttendanceProof(Base):
    __tablename__ = "attendance_proofs"

    attendance_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attendance_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    proof_type: Mapped[ProofType] = mapped_column(
        sa.Enum(ProofType, name="proof_type"), nullable=False
    )
    # MinIO object path: e.g. "attendance-proofs/entry_<emp_id>_2026-06-03.jpg"
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    attendance_event: Mapped["AttendanceEvent"] = relationship(
        "AttendanceEvent", back_populates="proofs"
    )
    employee: Mapped["Employee"] = relationship("Employee")
