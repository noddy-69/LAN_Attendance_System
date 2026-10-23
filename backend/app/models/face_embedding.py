import uuid

import sqlalchemy as sa
from sqlalchemy import Boolean, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 512-dimensional float vector produced by InsightFace ONNX model
    embedding: Mapped[list[float]] = mapped_column(
        ARRAY(Float), nullable=False
    )
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa.true()
    )

    employee: Mapped["Employee"] = relationship(
        "Employee", back_populates="face_embeddings"
    )
