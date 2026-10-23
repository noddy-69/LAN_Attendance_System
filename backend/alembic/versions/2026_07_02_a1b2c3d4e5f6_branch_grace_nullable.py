"""branch_grace_nullable

Make branches.grace_period_minutes nullable so a branch can *inherit* the org-wide
grace default instead of always carrying its own value.

  NULL   → inherit system_policies['attendance.grace_period_minutes'] (the Settings default)
  number → this branch's explicit override (0 = truly no grace)

The server default of "0" is dropped so newly-created branches that don't specify a
grace store NULL (inherit) rather than a silent 0. Existing rows keep their current
values (0 or an explicit number), so no branch's late-detection behaviour changes on
upgrade — inheritance is opt-in by clearing the field in the admin portal.

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "branches",
        "grace_period_minutes",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    # Restore NOT NULL: any inherited (NULL) rows fall back to 0 grace.
    op.execute("UPDATE branches SET grace_period_minutes = 0 WHERE grace_period_minutes IS NULL")
    op.alter_column(
        "branches",
        "grace_period_minutes",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="0",
    )
