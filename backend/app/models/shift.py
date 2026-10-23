import uuid
from datetime import time

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Integer, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ShiftDefinition(Base):
    __tablename__ = "shift_definitions"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    # Total minutes expected per day — used for overtime calculation
    required_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_overnight: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false()
    )
    # NULL → applies to all branches
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    branch: Mapped["Branch | None"] = relationship(
        "Branch", back_populates="shifts"
    )
    employees: Mapped[list["Employee"]] = relationship(
        "Employee", back_populates="shift"
    )
