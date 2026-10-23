"""
Notification Tasks
==================
Three-tier notification channel priority:

    WhatsApp (Meta Cloud API) → Email (SMTP) → In-App only

Flow for send_notification()
-----------------------------
  1.  Write a Notification row to DB (status=PENDING, channel=IN_APP).
      This is the base in-app record; it shows up in the portal feed
      regardless of whether WhatsApp / email delivery succeeds.

  2.  If the employee has a phone number and the WhatsApp Cloud API is configured,
      attempt WhatsApp delivery via the Meta WhatsApp Cloud API (graph.facebook.com).
        • Success → update status=SENT, channel=WHATSAPP, sent_at=now
        • Network error → status=QUEUED_OFFLINE (beat task retries)
        • Config / template error → fall through to email

  3.  If WhatsApp was not sent, attempt SMTP email (if configured).
        • Success → status=SENT, channel=EMAIL, sent_at=now
        • Network error → status=QUEUED_OFFLINE
        • Config error → status stays PENDING (in-app only, no retry needed)

  4.  If neither channel sent → notification stays as in-app PENDING.
      Status is QUEUED_OFFLINE only when a transient network error
      prevented an otherwise-configured channel from delivering.

retry_failed_notifications() (Celery beat, every 5 min)
---------------------------------------------------------
  Finds all QUEUED_OFFLINE records with retry_count < 3.
  Attempts delivery again (same WhatsApp → email → in-app cascade).
  After 3 failures: sets status=FAILED, error_message="Max retries exceeded".

DB access
---------
  Celery workers run synchronously; they use the psycopg2 (sync) driver,
  NOT asyncpg.  A dedicated SyncSessionLocal is built lazily from the same
  DATABASE_URL (with '+asyncpg' stripped).

All monetary amounts: never touched here — notifications contain text only.
Timestamps: stored and logged UTC; IST conversion is a frontend concern.
"""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx
from celery import Task
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.employee import Employee
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationEvent,
    NotificationStatus,
)
from app.tasks.celery_app import celery_app

log = logging.getLogger(__name__)

# ── Sync SQLAlchemy session (psycopg2, not asyncpg) ───────────────────────────
# Celery workers are synchronous; using asyncpg here would require a running
# asyncio event loop, which Celery does not provide by default.

_sync_factory: sessionmaker | None = None


def _get_session_factory() -> sessionmaker:
    """Lazily build the sync session factory the first time a task needs it."""
    global _sync_factory
    if _sync_factory is None:
        sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(
            sync_url,
            pool_size=3,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        _sync_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return _sync_factory


def _session() -> Session:
    return _get_session_factory()()


# ── Notification config (DB system_policies, with .env fallback) ─────────────
# Lets a non-technical admin set WhatsApp/SMTP credentials in Admin → Settings instead of
# editing .env. A policy value wins when set; otherwise we fall back to the env (settings)
# default. This keeps working across .env regeneration and reboots.
from dataclasses import dataclass


@dataclass
class _NotifCfg:
    whatsapp_enabled: bool
    email_enabled: bool
    wa_token: str            # Meta Cloud API access token
    wa_phone_number_id: str  # Meta "Phone number ID"
    wa_template: str         # approved template name (body has one {{1}} parameter)
    wa_language: str         # template language code, e.g. en_US
    wa_api_version: str      # Graph API version, e.g. v21.0
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_tls: bool


def _resolve_notif_config(session: Session) -> _NotifCfg:
    import json as _json
    from app.models.system import SystemPolicy

    rows = session.execute(
        select(SystemPolicy.key, SystemPolicy.value).where(
            SystemPolicy.key.like("notifications.%"),
            SystemPolicy.deleted_at.is_(None),
        )
    ).all()
    pol: dict[str, Any] = {}
    for k, v in rows:
        try:
            pol[k] = _json.loads(v)
        except Exception:
            pol[k] = v

    def _s(key: str, default: str) -> str:
        val = pol.get(f"notifications.{key}")
        return val.strip() if isinstance(val, str) and val.strip() else default

    def _b(key: str, default: bool) -> bool:
        val = pol.get(f"notifications.{key}")
        return val if isinstance(val, bool) else default

    try:
        port = int(pol.get("notifications.smtp_port") or settings.SMTP_PORT)
    except (TypeError, ValueError):
        port = settings.SMTP_PORT

    return _NotifCfg(
        whatsapp_enabled=_b("whatsapp_enabled", True),
        email_enabled=_b("email_enabled", True),
        wa_token=_s("wa_token", settings.WHATSAPP_TOKEN),
        wa_phone_number_id=_s("wa_phone_number_id", settings.WHATSAPP_PHONE_NUMBER_ID),
        wa_template=_s("wa_template", settings.WHATSAPP_TEMPLATE),
        wa_language=_s("wa_language", settings.WHATSAPP_LANGUAGE),
        wa_api_version=_s("wa_api_version", settings.WHATSAPP_API_VERSION),
        smtp_host=_s("smtp_host", settings.SMTP_HOST),
        smtp_port=port,
        smtp_user=_s("smtp_user", settings.SMTP_USER),
        smtp_password=_s("smtp_password", settings.SMTP_PASSWORD),
        smtp_from=_s("smtp_from", settings.SMTP_FROM),
        smtp_tls=_b("smtp_tls", settings.SMTP_TLS),
    )


# ── Message templates ─────────────────────────────────────────────────────────
# Each entry maps NotificationEvent value → (title, body_template).
# Missing context keys are replaced with "N/A" via _safe_format().

_TEMPLATES: dict[str, tuple[str, str]] = {
    NotificationEvent.ATTENDANCE_MARKED: (
        "Attendance Marked",
        "Your attendance has been recorded. Check-in: {check_in}.",
    ),
    NotificationEvent.ABSENT_ALERT: (
        "Marked Absent",
        "You were marked ABSENT for {date}. If this is incorrect, please submit an "
        "attendance correction request from your portal.",
    ),
    NotificationEvent.LATE_ARRIVAL: (
        "Late Arrival",
        "You arrived {late_time} late today. Please plan to arrive on time.",
    ),
    NotificationEvent.LEAVE_APPLIED: (
        "Leave Application Submitted",
        "Your {leave_type} request for {days} day(s) starting {start_date} has been submitted and is pending approval.",
    ),
    NotificationEvent.LEAVE_APPROVED: (
        "Leave Approved",
        "Your {leave_type} request for {days} day(s) starting {start_date} has been approved by {approver}.",
    ),
    NotificationEvent.LEAVE_REJECTED: (
        "Leave Request Rejected",
        "Your {leave_type} request has been rejected. Remarks: {remarks}.",
    ),
    NotificationEvent.REIMBURSEMENT_UPDATE: (
        "Reimbursement Update",
        "Your reimbursement claim '{claim_title}' (Rs {amount}) is now {status}.",
    ),
    NotificationEvent.PAYROLL_DEDUCTION: (
        "Salary Deduction Notice",
        "A deduction of Rs {amount} has been applied for {month} {year} "
        "({late_count} late day(s) -> {net_days} day(s) of pay deducted).",
    ),
    NotificationEvent.CORRECTION_STATUS: (
        "Attendance Correction Update",
        "Your attendance correction request for {date} has been {status}. {remarks}",
    ),
}


def _safe_format(template: str, context: dict[str, Any]) -> str:
    """Format a template string, substituting 'N/A' for any missing keys."""
    class _Default(dict):
        def __missing__(self, key):
            return "N/A"
    return template.format_map(_Default(context))


def _fmt_minutes(minutes: Any) -> str:
    """Format a minutes count as hours + minutes, e.g. 90 -> '1h 30m', 45 -> '45m'."""
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        return "N/A"
    h, mm = divmod(max(0, m), 60)
    return f"{h}h {mm:02d}m" if h else f"{mm}m"


def _get_title_body(event_type: str, context: dict[str, Any]) -> tuple[str, str]:
    """Return (title, body) for the given event type and context."""
    key = _normalise_event(event_type)
    title_tpl, body_tpl = _TEMPLATES.get(key, ("Notification", "{message}"))
    # Provide a friendly hours+minutes form of late_minutes for templates.
    if "late_minutes" in context and "late_time" not in context:
        context = {**context, "late_time": _fmt_minutes(context["late_minutes"])}
    return _safe_format(title_tpl, context), _safe_format(body_tpl, context)


def _normalise_event(raw: str) -> str:
    """Accept both enum name ('ATTENDANCE_MARKED') and value ('attendance_marked')."""
    v = raw.lower()
    # Check if it's a valid enum value
    try:
        NotificationEvent(v)
        return v
    except ValueError:
        pass
    # Try as enum name
    try:
        return NotificationEvent[raw.upper()].value
    except KeyError:
        return v


# ── WhatsApp (Meta Cloud API) ─────────────────────────────────────────────────


def _normalise_phone(phone: str) -> str:
    """Digits only, with country code, no '+' (Meta wants E.164 without the plus)."""
    digits = "".join(c for c in phone if c.isdigit())
    # Assume Indian numbers; prefix 91 if 10 digits (no country code)
    if len(digits) == 10:
        return "91" + digits
    return digits


def _send_whatsapp(cfg: "_NotifCfg", notif: Notification, phone: str, body: str) -> tuple[bool, bool]:
    """
    Send a WhatsApp message via the Meta WhatsApp Cloud API (graph.facebook.com).

    Uses an approved template (cfg.wa_template) with the message text as its single
    body parameter ({{1}}). Returns (sent, network_error): network_error=True is a
    transient failure (→ QUEUED_OFFLINE); (False, False) is a config/template error.
    """
    if not cfg.wa_token or not cfg.wa_phone_number_id:
        log.debug("WhatsApp Cloud API not configured — skipping WhatsApp")
        return False, False
    if not cfg.wa_template:
        log.warning("WhatsApp template name not set — skipping WhatsApp")
        return False, False

    to = _normalise_phone(phone)
    url = f"https://graph.facebook.com/{cfg.wa_api_version}/{cfg.wa_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": cfg.wa_template,
            "language": {"code": cfg.wa_language},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": body[:1024]}]}
            ],
        },
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {cfg.wa_token}",
                    "Content-Type": "application/json",
                },
            )

        if resp.status_code == 200:
            data = resp.json()
            if data.get("messages"):
                log.info(
                    "WhatsApp sent: employee=%s event=%s",
                    notif.employee_id, notif.event_type,
                )
                return True, False
            log.warning("WhatsApp 200 but no message id: %s — falling back to email", data)
            return False, False
        elif resp.status_code in (401, 403):
            log.error("WhatsApp auth error %d — check the access token", resp.status_code)
            return False, False
        elif 500 <= resp.status_code < 600:
            log.warning("WhatsApp HTTP %d — treating as transient", resp.status_code)
            return False, True    # transient → QUEUED_OFFLINE
        else:
            # 4xx (bad template / recipient / phone-number-id) = config error → fall through
            log.error("WhatsApp HTTP %d: %s", resp.status_code, resp.text[:300])
            return False, False

    except (httpx.ConnectError, httpx.TimeoutException, socket.gaierror) as exc:
        log.warning("WhatsApp network error: %s — will retry", exc)
        return False, True    # offline → QUEUED_OFFLINE
    except Exception as exc:
        log.error("WhatsApp unexpected error: %s", exc)
        return False, False   # unknown → don't retry forever


# ── Email (SMTP) ──────────────────────────────────────────────────────────────

def _send_email(cfg: "_NotifCfg", notif: Notification, to_email: str, title: str, body: str) -> tuple[bool, bool]:
    """
    Send email via SMTP.

    Returns (sent: bool, network_error: bool).
    """
    if not cfg.smtp_user or not cfg.smtp_password:
        log.debug("SMTP credentials not configured — skipping email")
        return False, False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = title
    msg["From"] = cfg.smtp_from
    msg["To"] = to_email

    text_part = MIMEText(body, "plain", "utf-8")
    html_body = f"<html><body><p>{body.replace(chr(10), '<br>')}</p></body></html>"
    html_part = MIMEText(html_body, "html", "utf-8")
    msg.attach(text_part)
    msg.attach(html_part)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            if cfg.smtp_tls:
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.sendmail(cfg.smtp_from, [to_email], msg.as_string())

        log.info(
            "Email sent: to=%s event=%s", to_email, notif.event_type
        )
        return True, False

    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected,
            ConnectionRefusedError, socket.gaierror, TimeoutError) as exc:
        log.warning("SMTP network error: %s — will retry", exc)
        return False, True    # transient → QUEUED_OFFLINE
    except smtplib.SMTPAuthenticationError as exc:
        log.error("SMTP auth error: %s — check SMTP_USER / SMTP_PASSWORD", exc)
        return False, False   # config error → don't retry
    except Exception as exc:
        log.error("Email unexpected error: %s", exc)
        return False, False


# ── Core dispatch logic (shared by send_notification + retry) ────────────────

def _dispatch(session: Session, notif: Notification, employee: Employee) -> None:
    """
    Attempt delivery in priority order: WhatsApp → Email → In-App.
    Mutates notif.status, notif.channel, notif.sent_at, notif.error_message.
    Does NOT commit — caller is responsible.
    """
    notif.last_attempted_at = datetime.now(timezone.utc)
    cfg = _resolve_notif_config(session)

    # ── WhatsApp ──────────────────────────────────────────────────────────────
    if cfg.whatsapp_enabled and employee.phone and cfg.wa_token and cfg.wa_phone_number_id:
        sent, is_network_err = _send_whatsapp(cfg, notif, employee.phone, notif.body)
        if sent:
            notif.channel = NotificationChannel.WHATSAPP
            notif.status = NotificationStatus.SENT
            notif.sent_at = datetime.now(timezone.utc)
            notif.error_message = None
            return
        if is_network_err:
            notif.status = NotificationStatus.QUEUED_OFFLINE
            notif.error_message = "WhatsApp: network error"
            # Don't return — also try email (belt-and-suspenders for offline)

    # ── Email ─────────────────────────────────────────────────────────────────
    if cfg.email_enabled and employee.email and cfg.smtp_user:
        sent, is_network_err = _send_email(cfg, notif, employee.email, notif.title, notif.body)
        if sent:
            notif.channel = NotificationChannel.EMAIL
            notif.status = NotificationStatus.SENT
            notif.sent_at = datetime.now(timezone.utc)
            notif.error_message = None
            return
        if is_network_err and notif.status != NotificationStatus.QUEUED_OFFLINE:
            notif.status = NotificationStatus.QUEUED_OFFLINE
            notif.error_message = "Email: network error"

    # ── In-App only ───────────────────────────────────────────────────────────
    # If neither WhatsApp nor email succeeded and we didn't set QUEUED_OFFLINE,
    # the notification stays as PENDING in-app (visible in the portal feed).
    if notif.status not in (NotificationStatus.QUEUED_OFFLINE, NotificationStatus.SENT):
        notif.channel = NotificationChannel.IN_APP
        notif.status = NotificationStatus.PENDING


# ── Celery task: send_notification ───────────────────────────────────────────

@celery_app.task(
    name="app.tasks.notifications.send_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def send_notification(
    self: Task,
    employee_id: str,
    event_type: str,
    reference_id: str | None = None,
    reference_type: str | None = None,
    **context,
) -> dict:
    """
    Main notification task.  Fire-and-forget: always creates an in-app record
    and best-efforts WhatsApp / email delivery.

    Parameters
    ----------
    employee_id   : UUID string of the recipient employee
    event_type    : NotificationEvent name or value (e.g. "ATTENDANCE_MARKED")
    reference_id  : optional UUID of the triggering entity (attendance, leave, etc.)
    reference_type: optional table name of the triggering entity
    **context     : event-specific data for message templating
                    e.g. check_in="09:01 IST", late_minutes=15

    Example
    -------
    send_notification.delay(
        str(employee.id),
        "ATTENDANCE_MARKED",
        check_in="09:01 IST",
        reference_id=str(daily_id),
        reference_type="daily_attendance",
    )
    """
    event_norm = _normalise_event(event_type)
    title, body = _get_title_body(event_norm, context)

    log.info(
        "send_notification: employee=%s event=%s title=%r",
        employee_id, event_norm, title,
    )

    with _session() as session:
        # ── Fetch employee ─────────────────────────────────────────────────────
        emp_uuid = uuid.UUID(employee_id)
        employee = session.execute(
            select(Employee).where(
                Employee.id == emp_uuid,
                Employee.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

        if not employee:
            log.warning("send_notification: employee %s not found — aborting", employee_id)
            return {"status": "aborted", "reason": "employee_not_found"}

        # ── Create Notification record (in-app base) ───────────────────────────
        notif = Notification(
            employee_id=emp_uuid,
            event_type=NotificationEvent(event_norm),
            title=title,
            body=body,
            channel=NotificationChannel.IN_APP,     # updated on delivery success
            status=NotificationStatus.PENDING,
            celery_task_id=self.request.id,
            reference_id=uuid.UUID(reference_id) if reference_id else None,
            reference_type=reference_type,
        )
        session.add(notif)
        session.flush()    # get notif.id without committing
        notif_id = str(notif.id)

        log.info(
            "Notification record created: id=%s employee=%s event=%s",
            notif_id, employee_id, event_norm,
        )

        # ── Attempt delivery ───────────────────────────────────────────────────
        _dispatch(session, notif, employee)

        session.commit()
        log.info(
            "Notification committed: id=%s status=%s channel=%s",
            notif_id, notif.status, notif.channel,
        )

    return {
        "notification_id": notif_id,
        "status": notif.status.value if notif.status else "unknown",
        "channel": notif.channel.value if notif.channel else "in_app",
    }


# ── Celery beat task: retry_failed_notifications ─────────────────────────────

@celery_app.task(
    name="app.tasks.notifications.retry_failed_notifications",
    acks_late=True,
)
def retry_failed_notifications() -> dict:
    """
    Celery beat task — fires every 5 minutes.

    Finds all QUEUED_OFFLINE notifications with retry_count < 3 and
    attempts delivery again.  After 3 failed attempts, sets status=FAILED.

    This handles the "offline fallback" scenario from CLAUDE.md:
    if no internet → store as in-app only, retry when internet is restored.
    """
    with _session() as session:
        candidates = session.execute(
            select(Notification)
            .where(
                Notification.status == NotificationStatus.QUEUED_OFFLINE,
                Notification.retry_count < 3,
                Notification.deleted_at.is_(None),
            )
            .limit(50)    # process at most 50 per beat cycle
        ).scalars().all()

        if not candidates:
            return {"retried": 0, "failed": 0}

        retried = failed = 0
        for notif in candidates:
            emp = session.execute(
                select(Employee).where(Employee.id == notif.employee_id)
            ).scalar_one_or_none()

            if not emp:
                notif.status = NotificationStatus.FAILED
                notif.error_message = "Employee not found"
                failed += 1
                continue

            notif.retry_count += 1
            prev_status = notif.status

            _dispatch(session, notif, emp)

            if notif.status == NotificationStatus.SENT:
                log.info(
                    "Retry succeeded: id=%s attempt=%d channel=%s",
                    notif.id, notif.retry_count, notif.channel,
                )
                retried += 1
            elif notif.retry_count >= 3:
                notif.status = NotificationStatus.FAILED
                notif.error_message = (
                    (notif.error_message or "") + " | Max retries (3) exceeded"
                ).lstrip(" | ")
                log.warning(
                    "Notification permanently failed: id=%s after %d attempts",
                    notif.id, notif.retry_count,
                )
                failed += 1
            else:
                # Still QUEUED_OFFLINE — will be retried in the next beat cycle
                log.info(
                    "Retry attempt %d failed for id=%s — will retry again",
                    notif.retry_count, notif.id,
                )

        session.commit()
        log.info(
            "retry_failed_notifications: retried=%d failed=%d remaining=%d",
            retried,
            failed,
            len(candidates) - retried - failed,
        )

    return {"retried": retried, "failed": failed}
