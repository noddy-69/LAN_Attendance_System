import enum
import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ReimbursementCategory(str, enum.Enum):
    TRAVEL = "travel"
    FOOD = "food"
    ACCOMMODATION = "accommodation"
    MEDICAL = "medical"
    OFFICE_SUPPLIES = "office_supplies"
    OTHER = "other"


class ReimbursementStatus(str, enum.Enum):
    PENDING_MANAGER = "pending_manager"
    PENDING_HR = "pending_hr"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class Reimbursement(Base):
    __tablename__ = "reimbursements"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stored in paise (integer) — never float
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[ReimbursementCategory] = mapped_column(
        sa.Enum(ReimbursementCategory, name="reimbursement_category"), nullable=False
    )
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[ReimbursementStatus] = mapped_column(
        sa.Enum(ReimbursementStatus, name="reimbursement_status"),
        nullable=False,
        default=ReimbursementStatus.PENDING_MANAGER,
        index=True,
    )

    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    manager_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    manager_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    hr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    hr_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hr_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    employee: Mapped["Employee"] = relationship(
        "Employee",
        back_populates="reimbursements",
        foreign_keys=[employee_id],
    )
    approving_manager: Mapped["Employee | None"] = relationship(
        "Employee", foreign_keys=[manager_id]
    )
    approving_hr: Mapped["Employee | None"] = relationship(
        "Employee", foreign_keys=[hr_id]
    )
    documents: Mapped[list["ReimbursementDocument"]] = relationship(
        "ReimbursementDocument", back_populates="reimbursement", cascade="all, delete-orphan"
    )


class ReimbursementDocument(Base):
    __tablename__ = "reimbursement_documents"

    reimbursement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reimbursements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # MinIO object path
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)

    reimbursement: Mapped[Reimbursement] = relationship(
        "Reimbursement", back_populates="documents"
    )
