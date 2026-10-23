import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class DeviceType(str, enum.Enum):
    CAMERA = "camera"
    BIOMETRIC = "biometric"


class Device(Base):
    __tablename__ = "devices"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    device_type: Mapped[DeviceType] = mapped_column(
        sa.Enum(DeviceType, name="device_type"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Camera fields — RTSP URL stored encrypted at rest
    rtsp_url_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_entry_camera: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )

    # Biometric device fields (ZKTeco K40 ADMS)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Device serial sent in ADMS payloads as "sn"
    device_uid: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    branch: Mapped["Branch"] = relationship("Branch", back_populates="devices")
    attendance_events: Mapped[list["AttendanceEvent"]] = relationship(
        "AttendanceEvent", back_populates="device"
    )
