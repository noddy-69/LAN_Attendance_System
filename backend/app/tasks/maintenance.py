"""
Maintenance beat task — automatic end-of-month database backup.

The beat fires daily; the task only performs a backup on the LAST day of the month
(when tomorrow, in IST, is the 1st), so each completed month is captured once.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.tasks.celery_app import celery_app

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


@celery_app.task(name="app.tasks.maintenance.monthly_backup", acks_late=True)
def monthly_backup() -> dict:
    today = datetime.now(IST).date()
    if (today + timedelta(days=1)).day != 1:
        return {"skipped": True, "reason": "not month-end", "date": str(today)}
    from app.services import data_service
    try:
        # Name the file by the completed month, e.g. backup_July_2026.dump
        month_name = today.strftime("%B_%Y")
        meta = data_service.create_backup(filename=f"backup_{month_name}.dump")
        log.info("monthly_backup created %s (%d bytes)", meta["filename"], meta["size_bytes"])
        return {"backed_up": True, **meta}
    except Exception as exc:  # noqa: BLE001 — log & report, don't crash the beat
        log.error("monthly_backup failed: %s", exc)
        return {"backed_up": False, "error": str(exc)}
