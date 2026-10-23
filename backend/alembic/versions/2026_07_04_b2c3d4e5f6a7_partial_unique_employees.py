"""partial_unique_employees

Make the employees email / employee_code / biometric_uid uniqueness apply ONLY to
non-deleted rows. A soft-deleted employee kept the same email/code/biometric UID under a
full unique constraint, so re-creating "the same" employee after deletion hit the DB
unique index and 500'd (the service dup-check ignores soft-deleted rows, but the DB did
not). Partial unique indexes (WHERE deleted_at IS NULL) let the historical soft-deleted
row coexist with a freshly-created active one.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the full unique constraints/index.
    op.drop_constraint("employees_employee_code_key", "employees", type_="unique")
    op.drop_constraint("employees_biometric_uid_key", "employees", type_="unique")
    op.drop_index("ix_employees_email", table_name="employees")

    # Recreate uniqueness as partial indexes — enforced only among active employees.
    op.create_index(
        "uq_employees_email_active", "employees", ["email"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_employees_code_active", "employees", ["employee_code"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_employees_biometric_active", "employees", ["biometric_uid"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Plain (non-unique) email index for lookups that may include deleted rows.
    op.create_index("ix_employees_email", "employees", ["email"])


def downgrade() -> None:
    op.drop_index("ix_employees_email", table_name="employees")
    op.drop_index("uq_employees_biometric_active", table_name="employees")
    op.drop_index("uq_employees_code_active", table_name="employees")
    op.drop_index("uq_employees_email_active", table_name="employees")
    op.create_index("ix_employees_email", "employees", ["email"], unique=True)
    op.create_unique_constraint("employees_biometric_uid_key", "employees", ["biometric_uid"])
    op.create_unique_constraint("employees_employee_code_key", "employees", ["employee_code"])
