import uuid

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class EmployeeHierarchy(Base):
    """Closure table for efficient ancestor/descendant queries.

    Each row stores one (employee, ancestor) pair at a given depth.
    depth=1 → direct manager, depth=2 → manager's manager, etc.
    """

    __tablename__ = "employee_hierarchy"
    __table_args__ = (
        UniqueConstraint("employee_id", "ancestor_id", name="uq_hierarchy_pair"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ancestor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False)

    employee: Mapped["Employee"] = relationship(
        "Employee", foreign_keys=[employee_id]
    )
    ancestor: Mapped["Employee"] = relationship(
        "Employee", foreign_keys=[ancestor_id]
    )
