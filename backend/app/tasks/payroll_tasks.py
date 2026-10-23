"""
Payroll Tasks
=============
Celery beat task that triggers monthly late-penalty deduction calculation
on the 1st of every month at 01:00 UTC.

The actual calculation logic lives in app.tasks.payroll.calculate_monthly_deductions
so it can be called from both this Celery task and integration tests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.tasks.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.payroll_tasks.run_monthly_payroll",
    acks_late=True,
)
def run_monthly_payroll(month: int | None = None, year: int | None = None) -> dict:
    """
    Calculate late-penalty deductions for ALL branches for the given month/year.
    Defaults to the previous calendar month when called by beat with no args.

    Delegates to calculate_monthly_deductions (branch_id=None → all branches).
    """
    from app.tasks.payroll import calculate_monthly_deductions

    now = datetime.now(timezone.utc)
    if month is None or year is None:
        first_this_month = now.replace(day=1)
        year  = first_this_month.year  if first_this_month.month > 1 else first_this_month.year - 1
        month = first_this_month.month - 1 if first_this_month.month > 1 else 12

    log.info("run_monthly_payroll: month=%d year=%d", month, year)

    result = calculate_monthly_deductions(branch_id=None, year=year, month=month)

    log.info(
        "run_monthly_payroll done: processed=%d affected=%d",
        result["processed"], result["affected"],
    )
    return result
