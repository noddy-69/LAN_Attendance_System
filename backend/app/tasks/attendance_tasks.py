"""
Attendance materialization task
===============================
`recalculate_daily_attendance` computes the full status (PRESENT/LATE/HALF_DAY from
events, and ABSENT/WEEKEND/HOLIDAY/ON_LEAVE from the calendar/leave context) — but it
only runs when an employee has a check-in event. So days with no check-in never get a
`daily_attendance` row: the calendar leaves them blank and reports undercount absences.

This daily beat task materializes a row for EVERY active employee for the day that just
ended, so absent/weekend/holiday/leave days are recorded. It is idempotent (the upsert
just recomputes), so re-running over a date range is safe — used by the admin "backfill".
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date as _date, datetime, timedelta, timezone

from sqlalchemy import select

from app.tasks.celery_app import celery_app

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def _materialize_day(ist_date: _date, notify: bool = False) -> int:
    """
    Upsert daily_attendance for every active employee for one IST date.

    When ``notify`` is True (the automatic nightly run), an ABSENT_ALERT notification is
    queued for each employee whose status *becomes* ABSENT on this run. Backfills pass
    notify=False so re-running over historical dates never blasts old absent alerts, and
    the prev-status guard means re-running the same day is a no-op for notifications.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.daily_attendance import AttendanceStatus, DailyAttendance
    from app.models.employee import Employee
    from app.models.role import Role
    from app.services import attendance_service

    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(Employee.id).where(
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
                Employee.date_of_joining <= ist_date,  # don't mark absent before joining
                # Skip non-attendance accounts: the face-service machine account and
                # admin accounts (system administrators aren't attendance-tracked staff).
                ~Employee.role.has(Role.name.in_(["service", "admin"])),
            )
        )
        emp_ids = [row[0] for row in res.all()]

    done = 0
    for emp_id in emp_ids:
        # Fresh session per employee so one failure can't poison the batch.
        async with AsyncSessionLocal() as session:
            try:
                prev_status = None
                if notify:
                    prev = await session.execute(
                        select(DailyAttendance.status).where(
                            DailyAttendance.employee_id == emp_id,
                            DailyAttendance.date == ist_date,
                        )
                    )
                    prev_status = prev.scalar_one_or_none()

                daily = await attendance_service.recalculate_daily_attendance(
                    session, emp_id, ist_date
                )
                # Read before commit — the async session may expire attributes on commit.
                new_status = daily.status
                daily_id = str(daily.id)
                await session.commit()
                done += 1

                if (
                    notify
                    and new_status == AttendanceStatus.ABSENT
                    and prev_status != AttendanceStatus.ABSENT
                ):
                    from app.tasks.notifications import send_notification
                    send_notification.delay(
                        str(emp_id),
                        "ABSENT_ALERT",
                        date=ist_date.strftime("%d %b %Y"),
                        reference_id=daily_id,
                        reference_type="daily_attendance",
                    )
            except Exception as exc:  # noqa: BLE001 — log & continue
                await session.rollback()
                log.error("materialize failed for %s on %s: %s", emp_id, ist_date, exc)
    return done


async def _materialize_range(start: _date, end: _date, notify: bool = False) -> int:
    total = 0
    d = start
    while d <= end:
        total += await _materialize_day(d, notify=notify)
        d += timedelta(days=1)
    return total


@celery_app.task(
    name="app.tasks.attendance_tasks.materialize_daily_attendance",
    acks_late=True,
)
def materialize_daily_attendance(
    target_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """
    Ensure a daily_attendance row exists for every active employee.

    - No args (beat): materializes *yesterday* in IST (the day that just completed).
    - target_date (YYYY-MM-DD): that single IST day.
    - target_date + end_date: an inclusive IST date range (backfill).
    """
    if target_date:
        start = _date.fromisoformat(target_date)
        end = _date.fromisoformat(end_date) if end_date else start
        notify = False  # explicit backfill — don't blast historical absent alerts
    else:
        start = end = (datetime.now(IST) - timedelta(days=1)).date()
        notify = True   # nightly run for the day that just ended

    log.info("materialize_daily_attendance: %s .. %s (notify=%s)", start, end, notify)
    n = asyncio.run(_materialize_range(start, end, notify=notify))
    log.info("materialize_daily_attendance done: %d employee-days", n)
    return {"from": str(start), "to": str(end), "employee_days": n}
