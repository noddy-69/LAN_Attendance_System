"""
Pure late-penalty deduction maths — no DB / async deps, shared by the on-demand
API service (payroll_service) and the Celery beat task (tasks.payroll).

Model ("percentage of a day's salary"):
    daily_salary = monthly_salary / salary_days_per_month
    units        = late_count // late_days_per_unit
    gross_days   = units * (penalty_percent_per_unit / 100)
    net_days     = max(0, gross_days - grace_days)
    deduction    = net_days * daily_salary

Money is INTEGER paise; fractional penalty-days are integer "centidays" (×100,
so 50 = 0.5 day, 150 = 1.5 days) to keep all arithmetic integer-only.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeductionPolicy:
    late_days_per_unit: int          # e.g. 3  → one penalty per 3 late days
    penalty_percent_per_unit: int    # e.g. 50 → each unit = 50% of a day's salary
    grace_days: float                # e.g. 1.5 → first 1.5 penalty-days forgiven
    salary_days_per_month: int       # e.g. 30 → a day's salary = monthly / 30


def compute_deduction(
    late_count: int,
    monthly_salary_paise: int,
    policy: DeductionPolicy,
) -> dict:
    """Return the computed deduction snapshot for one employee-month."""
    days = policy.salary_days_per_month if policy.salary_days_per_month > 0 else 30
    daily_salary_paise = (monthly_salary_paise or 0) // days

    per_unit = policy.late_days_per_unit
    units = (late_count // per_unit) if per_unit > 0 else 0

    gross_days_x100 = units * policy.penalty_percent_per_unit          # centidays
    grace_x100 = int(round(policy.grace_days * 100))
    net_days_x100 = max(0, gross_days_x100 - grace_x100)

    # round(daily × net_days/100) without float: integer round-half-up.
    total_deduction_paise = (daily_salary_paise * net_days_x100 + 50) // 100

    return {
        "daily_salary_paise": daily_salary_paise,
        "penalty_units": units,
        "net_penalty_days_x100": net_days_x100,
        "total_deduction_paise": total_deduction_paise,
    }
