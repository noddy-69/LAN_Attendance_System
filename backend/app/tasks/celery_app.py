"""
Celery application instance + beat schedule.

Broker:  Redis (same instance used by the rest of the stack)
Backend: Redis  (task result storage; kept 1 hour)

Beat tasks
----------
  retry_failed_notifications   every 5 minutes
  run_monthly_payroll          1st of every month at 01:00 UTC

Worker startup command (docker-compose):
  celery -A app.tasks.celery_app worker -B --loglevel=info --concurrency=2

The -B flag runs the beat scheduler in the same process as the worker.
For scaling to multiple workers, run beat as a separate process without -B
so only one beat instance fires periodic tasks.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "attendance",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.notifications",
        "app.tasks.payroll_tasks",
        "app.tasks.reports",
        "app.tasks.attendance_tasks",
        "app.tasks.maintenance",
    ],
)

celery_app.conf.update(
    # ── Serialisation ────────────────────────────────────────────────────────
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # ── Queue — all tasks go to "celery" (the built-in default). ─────────────
    # The worker command uses --queues=celery (or no --queues flag, which also
    # defaults to "celery").  Keeping one queue keeps the setup simple for ≤20 employees.
    task_default_queue="celery",

    # ── Reliability ───────────────────────────────────────────────────────────
    # ack_late: task is acknowledged AFTER it finishes (not before).
    # If the worker crashes mid-task, the message re-queues automatically.
    task_acks_late=True,
    worker_prefetch_multiplier=1,   # fetch only 1 task at a time per worker thread
    broker_connection_retry_on_startup=True,  # suppress Celery 5.x deprecation warning

    # ── Timestamps ────────────────────────────────────────────────────────────
    timezone="UTC",
    enable_utc=True,

    # ── Result TTL ────────────────────────────────────────────────────────────
    result_expires=3600,    # discard results after 1 hour to keep Redis lean

    # ── Beat schedule ─────────────────────────────────────────────────────────
    beat_schedule={
        # Retry notifications that failed due to network outage.
        # Runs every 5 minutes; individual tasks handle max-retry logic.
        "retry-failed-notifications": {
            "task": "app.tasks.notifications.retry_failed_notifications",
            "schedule": 300.0,   # seconds
        },
        # Monthly late-penalty deduction calculation.
        # Runs on the 1st of every month at 01:00 UTC.
        "monthly-payroll-deductions": {
            "task": "app.tasks.payroll_tasks.run_monthly_payroll",
            "schedule": crontab(hour=1, minute=0, day_of_month=1),
        },
        # Materialize daily_attendance for the day that just ended so absent / weekend /
        # holiday / leave days get a row (calendar + reports). 19:00 UTC = 00:30 IST.
        "materialize-daily-attendance": {
            "task": "app.tasks.attendance_tasks.materialize_daily_attendance",
            "schedule": crontab(hour=19, minute=0),
        },
        # Automatic end-of-month backup. Fires daily at 18:15 UTC (23:45 IST); the task
        # only backs up on the last day of the month.
        "monthly-backup": {
            "task": "app.tasks.maintenance.monthly_backup",
            "schedule": crontab(hour=18, minute=15),
        },
    },
)
