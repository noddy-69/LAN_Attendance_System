"""add_absent_alert_notification_event

Adds the 'ABSENT_ALERT' value to the notification_event PostgreSQL ENUM.

Employees no longer receive a notification every day their attendance is marked.
Instead, the nightly materialization task emits an ABSENT_ALERT for any employee who
is marked ABSENT for the completed day, so push (WhatsApp/email) traffic is limited to
exceptions worth acting on.

As with the other enum values, SQLAlchemy's Enum persists the Python member NAME, so
the new label is the uppercase 'ABSENT_ALERT' (not the lowercase value). PostgreSQL 12+
allows ALTER TYPE ... ADD VALUE inside a transaction as long as the new value isn't used
in the same transaction; ADD VALUE IF NOT EXISTS makes it idempotent.

Revision ID: e0f1a2b3c4d5
Revises: d8e9f0a1b2c3
Create Date: 2026-06-25

"""
from typing import Sequence, Union

from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_event ADD VALUE IF NOT EXISTS 'ABSENT_ALERT'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an ENUM without recreating the type.
    # Removing a still-referenced value is unsafe, so this is a no-op downgrade.
    pass
