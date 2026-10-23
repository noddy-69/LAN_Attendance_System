"""add_selfie_attendance_source

Adds the 'SELFIE' value to the attendance_source PostgreSQL ENUM, backing the
self-service LAN-gated selfie check-in attendance method.

The enum labels mirror the Python member NAMES (FACE_RECOGNITION, BIOMETRIC,
MANUAL) — that is what SQLAlchemy's Enum persists — so the new label must be the
uppercase NAME 'SELFIE', not the lowercase value.

PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction block as long
as the new value is not *used* in that same transaction (it isn't here — only
the label is added). ADD VALUE IF NOT EXISTS makes the migration idempotent.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-06-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE attendance_source ADD VALUE IF NOT EXISTS 'SELFIE'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an ENUM without recreating the type.
    # Removing a still-referenced value is unsafe, so this is a no-op downgrade.
    pass
