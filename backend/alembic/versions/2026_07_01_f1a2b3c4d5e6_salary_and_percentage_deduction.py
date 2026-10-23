"""salary_and_percentage_deduction

Adds per-employee monthly salary and reshapes salary_deductions for the new
"percentage of a day's salary" late-penalty model:

  units        = late_count // late_days_per_unit          (e.g. every 3 lates)
  gross_days   = units * penalty_percent_per_unit / 100    (e.g. 50% = half day each)
  net_days     = max(0, gross_days - grace_days)           (e.g. 1.5 grace days)
  daily_salary = monthly_salary / salary_days_per_month    (e.g. monthly / 30)
  deduction    = net_days * daily_salary

The four parameters live in system_policies (editable in the admin portal); the
per-employee monthly salary lives on the employees row. Money stays INTEGER paise;
fractional penalty-days are stored as integer "centidays" (×100, e.g. 50 = 0.5 day).

The legacy per-late columns (allowed_late_count, penalty_per_late_paise) are kept for
historical rows but made nullable — the new model no longer writes them.

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-07-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-employee monthly salary (paise). Default 0 so existing rows stay valid.
    op.add_column(
        "employees",
        sa.Column("monthly_salary_paise", sa.Integer(), nullable=False, server_default="0"),
    )

    # New deduction snapshot columns.
    op.add_column("salary_deductions", sa.Column("monthly_salary_paise", sa.Integer(), nullable=True))
    op.add_column("salary_deductions", sa.Column("daily_salary_paise", sa.Integer(), nullable=True))
    op.add_column(
        "salary_deductions",
        sa.Column("penalty_units", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "salary_deductions",
        sa.Column("net_penalty_days_x100", sa.Integer(), nullable=False, server_default="0"),
    )

    # Legacy per-late columns: keep for history, but the new model doesn't set them.
    op.alter_column("salary_deductions", "allowed_late_count", existing_type=sa.Integer(), nullable=True)
    op.alter_column("salary_deductions", "penalty_per_late_paise", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("salary_deductions", "penalty_per_late_paise", existing_type=sa.Integer(), nullable=False)
    op.alter_column("salary_deductions", "allowed_late_count", existing_type=sa.Integer(), nullable=False)
    op.drop_column("salary_deductions", "net_penalty_days_x100")
    op.drop_column("salary_deductions", "penalty_units")
    op.drop_column("salary_deductions", "daily_salary_paise")
    op.drop_column("salary_deductions", "monthly_salary_paise")
    op.drop_column("employees", "monthly_salary_paise")
