"""Device (camera + biometric) CRUD and connection-test service."""
import asyncio
import base64
import hashlib
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.branch import Branch
from app.models.device import Device, DeviceType
from app.models.system import AuditAction, AuditLog
from app.schemas.common import PaginationMeta
from app.schemas.devices import DeviceCreate, DeviceUpdate
from app.utils.pagination import paginate


# ── RTSP URL encryption ───────────────────────────────────────────────────────

def _fernet() -> Fernet:
    """Derive a Fernet key from SECRET_KEY via SHA-256 (produces required 32 bytes)."""
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    )
    return Fernet(key)


def _encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ""


def _mask_rtsp_url(url: str) -> str:
    """Replace the password part of an RTSP URL with *** for safe display."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.password:
            safe_netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                safe_netloc += f":{parsed.port}"
            return url.replace(
                f"{parsed.username}:{parsed.password}@", f"{parsed.username}:***@"
            )
    except Exception:
        pass
    return url


# ── Persistence helpers ───────────────────────────────────────────────────────

_EAGER = [selectinload(Device.branch)]


async def _get_or_404(db: AsyncSession, device_id: uuid.UUID) -> Device:
    result = await db.execute(
        select(Device)
        .where(Device.id == device_id, Device.deleted_at.is_(None))
        .options(*_EAGER)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise NotFoundError(f"Device {device_id} not found")
    return device


async def list_devices(
    db: AsyncSession,
    device_type: DeviceType | None = None,
    branch_id: uuid.UUID | None = None,
    per_page: int = 20,
    cursor: str | None = None,
) -> tuple[list[Device], PaginationMeta]:
    stmt = (
        select(Device)
        .where(Device.deleted_at.is_(None))
        .options(*_EAGER)
    )
    if device_type:
        stmt = stmt.where(Device.device_type == device_type)
    if branch_id:
        stmt = stmt.where(Device.branch_id == branch_id)
    return await paginate(db, stmt, Device, per_page, cursor)


async def get_device(db: AsyncSession, device_id: uuid.UUID) -> Device:
    return await _get_or_404(db, device_id)


def _decrypted_rtsp(device: Device) -> str | None:
    """Return plaintext RTSP URL or None if not set."""
    if not device.rtsp_url_encrypted:
        return None
    return _decrypt(device.rtsp_url_encrypted) or None


def masked_rtsp(device: Device) -> str | None:
    plaintext = _decrypted_rtsp(device)
    if not plaintext:
        return None
    return _mask_rtsp_url(plaintext)


async def create_device(db: AsyncSession, data: DeviceCreate) -> Device:
    branch = await db.execute(
        select(Branch.id).where(Branch.id == data.branch_id, Branch.deleted_at.is_(None))
    )
    if not branch.scalar_one_or_none():
        raise NotFoundError(f"Branch {data.branch_id} not found")

    if data.device_uid:
        dup = await db.execute(
            select(Device.id).where(
                Device.device_uid == data.device_uid,
                Device.deleted_at.is_(None),
            )
        )
        if dup.scalar_one_or_none():
            raise ConflictError(f"Device UID '{data.device_uid}' already registered")

    device = Device(
        name=data.name,
        device_type=data.device_type,
        branch_id=data.branch_id,
        is_entry_camera=data.is_entry_camera,
        rtsp_url_encrypted=_encrypt(data.rtsp_url) if data.rtsp_url else None,
        ip_address=data.ip_address,
        port=data.port,
        serial_number=data.serial_number,
        device_uid=data.device_uid,
        is_active=True,
    )
    db.add(device)
    await db.flush()
    return await _get_or_404(db, device.id)


async def update_device(
    db: AsyncSession, device_id: uuid.UUID, data: DeviceUpdate
) -> Device:
    device = await _get_or_404(db, device_id)
    updates = data.model_dump(exclude_unset=True)

    if "rtsp_url" in updates:
        device.rtsp_url_encrypted = (
            _encrypt(updates.pop("rtsp_url")) if updates["rtsp_url"] else None
        )
        updates.pop("rtsp_url", None)

    if "device_uid" in updates and updates["device_uid"] != device.device_uid:
        dup = await db.execute(
            select(Device.id).where(
                Device.device_uid == updates["device_uid"],
                Device.id != device_id,
                Device.deleted_at.is_(None),
            )
        )
        if dup.scalar_one_or_none():
            raise ConflictError(f"Device UID '{updates['device_uid']}' already registered")

    for field, value in updates.items():
        setattr(device, field, value)

    await db.flush()
    return await _get_or_404(db, device_id)


async def record_heartbeat(db: AsyncSession, device_id: uuid.UUID) -> Device:
    """Stamp the device's last_heartbeat to now. Called by the face service per camera."""
    device = await _get_or_404(db, device_id)
    device.last_heartbeat = datetime.now(timezone.utc)
    await db.flush()
    # Re-fetch with the branch eager-loaded — the UPDATE expires server-side
    # columns (updated_at) which would otherwise lazy-load outside the async ctx.
    return await _get_or_404(db, device_id)


async def delete_device(
    db: AsyncSession,
    device_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    device = await _get_or_404(db, device_id)
    before_val = {"name": device.name, "device_type": device.device_type.value,
                  "is_active": str(device.is_active)}
    device.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    audit = AuditLog(
        table_name="devices",
        record_id=device_id,
        action=AuditAction.DELETE,
        before_value=before_val,
        after_value={"deleted_at": str(device.deleted_at)},
        performed_by_id=actor_id,
    )
    db.add(audit)
    await db.flush()


# ── Connection test ───────────────────────────────────────────────────────────

async def _tcp_reachable(host: str, port: int, timeout: float = 5.0) -> tuple[bool, int]:
    """TCP connect probe. Returns (reachable, latency_ms)."""
    t0 = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        latency = int((time.monotonic() - t0) * 1000)
        return True, latency
    except Exception:
        latency = int((time.monotonic() - t0) * 1000)
        return False, latency


async def test_connection(
    db: AsyncSession, device_id: uuid.UUID
) -> dict:
    device = await _get_or_404(db, device_id)

    if device.device_type == DeviceType.CAMERA:
        rtsp = _decrypted_rtsp(device)
        if not rtsp:
            return {"reachable": False, "message": "No RTSP URL configured", "latency_ms": None}
        try:
            parsed = urllib.parse.urlparse(rtsp)
            host = parsed.hostname
            port = parsed.port or 554
        except Exception:
            return {"reachable": False, "message": "Invalid RTSP URL", "latency_ms": None}
        reachable, latency = await _tcp_reachable(host, port)
        msg = f"TCP {host}:{port} {'reachable' if reachable else 'unreachable'}"
        return {"reachable": reachable, "message": msg, "latency_ms": latency}

    else:  # BIOMETRIC
        if not device.ip_address:
            return {"reachable": False, "message": "No IP address configured", "latency_ms": None}
        port = device.port or 4370  # ZKTeco default ADMS port
        reachable, latency = await _tcp_reachable(device.ip_address, port)
        msg = f"TCP {device.ip_address}:{port} {'reachable' if reachable else 'unreachable'}"
        return {"reachable": reachable, "message": msg, "latency_ms": latency}
