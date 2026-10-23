import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class EventType(str, enum.Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class AttendanceSource(str, enum.Enum):
    FACE_RECOGNITION = "face_recognition"
    BIOMETRIC = "biometric"
    MANUAL = "manual"
    # Self-service selfie check-in from the employee's own device (LAN-gated)
    SELFIE = "selfie"


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL when source is manual or biometric (no physical device record)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[EventType] = mapped_column(
        sa.Enum(EventType, name="attendance_event_type"), nullable=False
    )
    source: Mapped[AttendanceSource] = mapped_column(
        sa.Enum(AttendanceSource, name="attendance_source"), nullable=False
    )

    # Original timestamp from the device (stored UTC)
    raw_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # Overwritten by HR after a correction request
    corrected_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Face-recognition specific
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Biometric specific — ZKTeco UID from ADMS payload
    biometric_uid: Mapped[str | None] = mapped_column(String(50), nullable=True)

    employee: Mapped["Employee"] = relationship(
        "Employee",
        back_populates="attendance_events",
        foreign_keys=[employee_id],
    )
    device: Mapped["Device | None"] = relationship(
        "Device", back_populates="attendance_events"
    )
    proofs: Mapped[list["AttendanceProof"]] = relationship(
        "AttendanceProof", back_populates="attendance_event"
    )
