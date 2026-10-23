"""MinIO storage service — sync SDK wrapped in asyncio.to_thread."""
import asyncio
import io
import json
import uuid
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

# Supported MIME types for avatar uploads
AVATAR_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_EXT_MAP = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


# ── MinIO client factory ──────────────────────────────────────────────────────

def _client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def _init_bucket_sync() -> None:
    """Create bucket and set public-read policy on avatars/ prefix if needed."""
    client = _client()
    bucket = settings.MINIO_BUCKET_ATTENDANCE
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    # Allow anonymous GET on avatars — served publicly through Nginx /media/ proxy.
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/avatars/*"],
            }
        ],
    }
    try:
        client.set_bucket_policy(bucket, json.dumps(policy))
    except S3Error:
        pass  # policy may already be set or identical


async def init_bucket() -> None:
    """Async wrapper — call once at startup from the FastAPI lifespan."""
    await asyncio.to_thread(_init_bucket_sync)


# ── Avatar upload ─────────────────────────────────────────────────────────────

def _upload_sync(object_name: str, data: bytes, content_type: str) -> None:
    client = _client()
    client.put_object(
        settings.MINIO_BUCKET_ATTENDANCE,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


async def upload_avatar(
    employee_id: uuid.UUID, data: bytes, content_type: str
) -> str:
    """
    Upload avatar bytes to MinIO and return the public URL path stored in DB.

    The avatar is accessible at:
        {BASE_URL}/media/{bucket}/avatars/{employee_id}.{ext}
    """
    if content_type not in AVATAR_MIME_TYPES:
        from app.core.exceptions import UnprocessableError
        raise UnprocessableError(
            f"Unsupported image type. Allowed: {', '.join(AVATAR_MIME_TYPES)}"
        )

    ext = _EXT_MAP[content_type]
    object_name = f"avatars/{employee_id}.{ext}"
    await asyncio.to_thread(_upload_sync, object_name, data, content_type)

    # Relative, same-origin path (see _presigned_sync) so avatars load over http or https
    # regardless of BASE_URL — served through the Nginx /media/ proxy.
    bucket = settings.MINIO_BUCKET_ATTENDANCE
    return f"/media/{bucket}/{object_name}"


# ── Receipt upload (reimbursement documents — private, presigned access only) ─

# Receipts are not public; always use presigned URLs for access.
RECEIPT_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


async def upload_receipt(
    reimbursement_id: uuid.UUID,
    slot_id: uuid.UUID,
    filename: str,
    data: bytes,
    content_type: str,
) -> str:
    """
    Upload a reimbursement receipt to MinIO.
    Returns the MinIO object name (stored in DB as ReimbursementDocument.file_path).
    Access is always via presigned URL — receipts are NOT public.
    """
    from app.core.exceptions import UnprocessableError

    if content_type not in RECEIPT_MIME_TYPES:
        raise UnprocessableError(
            f"Unsupported file type. Allowed: {', '.join(sorted(RECEIPT_MIME_TYPES))}"
        )
    # Sanitise the original filename (keep extension, drop path components)
    safe_name = filename.replace("/", "_").replace("\\", "_")
    object_name = f"receipts/{reimbursement_id}/{slot_id}_{safe_name}"
    await asyncio.to_thread(_upload_sync, object_name, data, content_type)
    return object_name


# ── Correction proof upload (attendance-correction evidence — private) ────────

async def upload_correction_proof(
    daily_id: uuid.UUID,
    slot_id: uuid.UUID,
    filename: str,
    data: bytes,
    content_type: str,
) -> str:
    """
    Upload an optional attendance-correction proof (image/PDF) to MinIO.
    Returns the MinIO object name (stored in the correction JSON as proof_path).
    Access is always via presigned URL — proofs are NOT public.
    """
    from app.core.exceptions import UnprocessableError

    if content_type not in RECEIPT_MIME_TYPES:
        raise UnprocessableError(
            f"Unsupported file type. Allowed: {', '.join(sorted(RECEIPT_MIME_TYPES))}"
        )
    safe_name = filename.replace("/", "_").replace("\\", "_")
    object_name = f"corrections/{daily_id}/{slot_id}_{safe_name}"
    await asyncio.to_thread(_upload_sync, object_name, data, content_type)
    return object_name


# ── Proof frame upload (face recognition) ────────────────────────────────────

async def upload_proof_frame(object_name: str, data: bytes) -> None:
    """Upload a face-recognition proof frame. object_name is the full MinIO path."""
    await asyncio.to_thread(_upload_sync, object_name, data, "image/jpeg")


# ── Presigned URL (read-only, time-limited) ───────────────────────────────────

def _presigned_sync(object_name: str, expires_hours: int = 1) -> str:
    client = _client()
    url = client.presigned_get_object(
        settings.MINIO_BUCKET_ATTENDANCE,
        object_name,
        expires=timedelta(hours=expires_hours),
    )
    # Rewrite internal MinIO URL to be publicly accessible via Nginx /media/ proxy.
    # minio SDK generates: http://minio:9000/{bucket}/{object}?X-Amz-...
    # Nginx proxies /media/ → http://minio:9000/ with Host: minio:9000,
    # so the presigned signature remains valid (MinIO sees the same canonical host).
    scheme = "https" if settings.MINIO_SECURE else "http"
    internal_base = f"{scheme}://{settings.MINIO_ENDPOINT}/"
    # Return a RELATIVE, same-origin path so the browser loads the image from whatever
    # origin it is on (http://localhost, http://<lan-ip>, or the HTTPS domain). Embedding
    # an absolute BASE_URL here broke proof images when the app is opened over HTTPS while
    # BASE_URL still points at http://<ip> (mixed-content block / 301 redirect).
    public_base = "/media/"
    if url.startswith(internal_base):
        url = public_base + url[len(internal_base):]
    return url


async def get_presigned_url(object_name: str, expires_hours: int = 1) -> str:
    """Return a presigned GET URL valid for `expires_hours` hours (default 1)."""
    return await asyncio.to_thread(_presigned_sync, object_name, expires_hours)
