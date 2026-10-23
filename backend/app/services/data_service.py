"""
Data management service — full-database backup / restore + a "delete all data" reset.

Backup/restore use pg_dump / pg_restore (PostgreSQL custom format), so a restore is a
byte-exact rebuild of the schema + data with no schema mismatch. Dumps live in the
bind-mounted /backups directory (persisted on the host, copyable off-machine).
"""
from __future__ import annotations

import asyncio
import glob
import os
import re
import subprocess
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, UnprocessableError

BACKUP_DIR = os.environ.get("BACKUP_DIR", "/backups")
_FNAME_RE = re.compile(r"^backup_[0-9A-Za-z_\-]+\.dump$")

# Transactional tables wiped by a "delete data" reset (child → parent order).
# This clears only ATTENDANCE, LEAVE, REIMBURSEMENT and PAYROLL event data plus the
# notifications those events generated. Everything else is KEPT — in particular:
#   • employees (roster + profile pictures / avatar_url)  • face_embeddings (enrolment)
#   • employee_hierarchy (reporting lines)                • audit_logs (compliance trail)
#   • all config/setup (roles, permissions, branches, departments, devices,
#     leave_types, shift_definitions, holiday_calendar, system_policies)
_WIPE_TABLES = [
    "attendance_proofs",
    "attendance_events",
    "daily_attendance",
    "reimbursement_documents",
    "reimbursements",
    "leave_requests",
    "leave_balances",
    "salary_deductions",
    "notifications",
]


def _conn() -> dict:
    """Parse DATABASE_URL into pg_dump/pg_restore connection parts."""
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    p = urlparse(url)
    return {
        "host": p.hostname or "postgres",
        "port": str(p.port or 5432),
        "user": unquote(p.username or ""),
        "password": unquote(p.password or ""),
        "db": (p.path or "/").lstrip("/") or "attendance",
    }


def _base_args(c: dict) -> list[str]:
    return ["-h", c["host"], "-p", c["port"], "-U", c["user"], "-d", c["db"]]


def _env(c: dict) -> dict:
    return {**os.environ, "PGPASSWORD": c["password"]}


def _backup_meta(path: str) -> dict:
    st = os.stat(path)
    return {
        "filename": os.path.basename(path),
        "size_bytes": st.st_size,
        "created_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
    }


def list_backups() -> list[dict]:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    files = glob.glob(os.path.join(BACKUP_DIR, "backup_*.dump"))
    files.sort(key=os.path.getmtime, reverse=True)
    return [_backup_meta(f) for f in files]


_PG_DUMP_MAGIC = b"PGDMP"          # custom-format pg_dump files start with this
_MAX_UPLOAD_BYTES = 256 * 1024 * 1024  # 256 MB safety cap for uploaded backups


def save_uploaded_backup(data: bytes) -> str:
    """
    Validate an uploaded pg_dump (custom-format) file and store it in BACKUP_DIR so it
    can be restored like any server-side backup. Returns the stored filename (which
    matches _FNAME_RE, so restore_from accepts it).

    Rejects anything that isn't a custom-format dump created by this app's backup — the
    file must start with the PostgreSQL custom-format magic bytes.
    """
    if not data:
        raise UnprocessableError("The uploaded backup file is empty.")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise UnprocessableError("Backup file is too large to upload.")
    if data[:5] != _PG_DUMP_MAGIC:
        raise UnprocessableError(
            "That doesn't look like a valid backup. Upload a .dump file created by "
            "this system's Backup feature."
        )
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"backup_{ts}_upload.dump"
    path = os.path.join(BACKUP_DIR, fname)
    with open(path, "wb") as fh:
        fh.write(data)
    return fname


def create_backup(label: str = "", filename: str | None = None) -> dict:
    """Run pg_dump (custom format) into /backups and return the file metadata.

    Pass `filename` (must match _FNAME_RE) to use a fixed name — e.g. the automatic
    month-end backup names its file by month so it overwrites cleanly each month.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    c = _conn()
    if filename:
        if not _FNAME_RE.match(filename):
            raise UnprocessableError("Invalid backup filename.")
        fname = filename
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^0-9A-Za-z_\-]", "", label)[:32]
        fname = f"backup_{ts}{('_' + safe) if safe else ''}.dump"
    path = os.path.join(BACKUP_DIR, fname)
    proc = subprocess.run(
        ["pg_dump", *_base_args(c), "-Fc", "-f", path],
        env=_env(c), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        # Clean up a partial file so it can't be restored later.
        if os.path.exists(path):
            os.remove(path)
        raise UnprocessableError(f"Backup failed: {proc.stderr.strip()[:500]}")
    return _backup_meta(path)


def dump_to_path(path: str) -> None:
    """Run pg_dump (custom format) to an arbitrary path — used for an instant download
    that is NOT kept on the server (the caller streams it and deletes it)."""
    c = _conn()
    proc = subprocess.run(
        ["pg_dump", *_base_args(c), "-Fc", "-f", path],
        env=_env(c), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        if os.path.exists(path):
            os.remove(path)
        raise UnprocessableError(f"Backup failed: {proc.stderr.strip()[:500]}")


async def restore_latest(engine) -> dict:
    backups = list_backups()
    if not backups:
        raise UnprocessableError("No backup found to restore from.")
    return await restore_from(backups[0]["filename"], engine)


async def restore_from(filename: str, engine) -> dict:
    """pg_restore --clean the given dump, then reset the connection pool."""
    if not _FNAME_RE.match(filename):
        raise UnprocessableError("Invalid backup filename.")
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(path):
        raise NotFoundError(f"Backup '{filename}' not found.")

    c = _conn()
    # pg_restore --clean must DROP/CREATE every table, which needs exclusive locks.
    # The caller commits the request's own session first (so its auth query no longer
    # holds a lock); we then dispose idle pool connections and run with a bounded
    # lock_timeout, so pg_restore briefly waits for any transient app query instead of
    # hanging forever. (Terminating connections is avoided — it would kill this very
    # request's connection and 500 the response even though the restore succeeded.)
    proc = await asyncio.to_thread(
        subprocess.run,
        ["pg_restore", *_base_args(c),
         "--clean", "--if-exists", "--no-owner", "--no-privileges", path],
        env={**_env(c), "PGOPTIONS": "-c lock_timeout=20000"},
        capture_output=True, text=True, timeout=600,
    )
    # pg_restore returns non-zero for benign issues too; only treat as failure on a
    # genuine ERROR. Ignore the harmless ones:
    #   • "does not exist, skipping"       — --clean --if-exists on absent objects
    #   • "unrecognized configuration parameter" — a newer client (e.g. pg17 on Debian)
    #     emits SETs like transaction_timeout that the pinned PG16 server doesn't know;
    #     the SET fails but the data restores correctly.
    _benign = ("does not exist, skipping", "unrecognized configuration parameter")
    stderr = proc.stderr or ""
    fatal = [
        ln for ln in stderr.splitlines()
        if "error:" in ln.lower() and not any(b in ln.lower() for b in _benign)
    ]
    if proc.returncode != 0 and fatal:
        raise UnprocessableError("Restore failed: " + " | ".join(fatal[:5])[:600])

    # The tables were dropped & recreated — drop all pooled connections (and their
    # cached statement plans) so subsequent queries use the restored schema/data.
    await engine.dispose()
    return {"restored_from": filename, "warnings": len(stderr.splitlines())}


async def reset_all_data(db: AsyncSession) -> dict:
    """
    Delete transactional event data only — attendance, leave, reimbursements,
    corrections, payroll deductions and the notifications those events generated.

    Employees (including their profile pictures), enrolled face embeddings, reporting
    hierarchy, audit logs and all setup/config are PRESERVED. After a reset every
    employee still exists, can still log in, and stays enrolled for face recognition;
    only their attendance/leave/reimbursement/payroll history is cleared.
    """
    existing = set(
        (await db.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        )).scalars().all()
    )
    deleted: dict[str, int] = {}
    for tbl in _WIPE_TABLES:
        if tbl in existing:
            res = await db.execute(text(f"DELETE FROM {tbl}"))
            deleted[tbl] = res.rowcount or 0

    await db.flush()
    return {"status": "reset_complete", "deleted": deleted}
