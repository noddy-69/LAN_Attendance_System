"""leave_halfday_support

Adds is_half_day boolean to leave_requests and changes days_requested /
leave_balance day columns from INTEGER to NUMERIC(5,1) to support
0.5-day increments.

Revision ID: a5b2c3d4e5f6
Revises: 7ea8521385fd
Create Date: 2026-06-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a5b2c3d4e5f6"
down_revision: Union[str, None] = "7ea8521385fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leave_requests",
        sa.Column("is_half_day", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column(
        "leave_requests",
        "days_requested",
        type_=sa.Numeric(5, 1),
        existing_type=sa.Integer(),
        existing_nullable=False,
        postgresql_using="days_requested::numeric(5,1)",
    )
    op.alter_column(
        "leave_balances",
        "allocated_days",
        type_=sa.Numeric(5, 1),
        existing_type=sa.Integer(),
        existing_nullable=False,
        postgresql_using="allocated_days::numeric(5,1)",
    )
    op.alter_column(
        "leave_balances",
        "used_days",
        type_=sa.Numeric(5, 1),
        existing_type=sa.Integer(),
        existing_nullable=False,
        existing_server_default="0",
        postgresql_using="used_days::numeric(5,1)",
    )
    op.alter_column(
        "leave_balances",
        "carried_forward_days",
        type_=sa.Numeric(5, 1),
        existing_type=sa.Integer(),
        existing_nullable=False,
        existing_server_default="0",
        postgresql_using="carried_forward_days::numeric(5,1)",
    )


def downgrade() -> None:
    op.alter_column(
        "leave_balances",
        "carried_forward_days",
        type_=sa.Integer(),
        existing_type=sa.Numeric(5, 1),
        existing_nullable=False,
        postgresql_using="carried_forward_days::integer",
    )
    op.alter_column(
        "leave_balances",
        "used_days",
        type_=sa.Integer(),
        existing_type=sa.Numeric(5, 1),
        existing_nullable=False,
        postgresql_using="used_days::integer",
    )
    op.alter_column(
        "leave_balances",
        "allocated_days",
        type_=sa.Integer(),
        existing_type=sa.Numeric(5, 1),
        existing_nullable=False,
        postgresql_using="allocated_days::integer",
    )
    op.alter_column(
        "leave_requests",
        "days_requested",
        type_=sa.Integer(),
        existing_type=sa.Numeric(5, 1),
        existing_nullable=False,
        postgresql_using="days_requested::integer",
    )
    op.drop_column("leave_requests", "is_half_day")
