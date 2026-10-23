from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# JWT algorithm is a system constant, not operator configuration.
JWT_ALGORITHM = "HS256"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        frozen=True,  # settings are immutable after construction
    )

    # ── Deployment ────────────────────────────────────────
    # This on-prem product runs on the office LAN only. The same env var also selects
    # the nginx conf file: "local" loads local.conf (plain HTTP), "local-ssl" loads
    # local-ssl.conf (HTTPS, set by setup-https.ps1). The backend does not branch on
    # this, but it must accept "local-ssl" or it would crash on boot after HTTPS is
    # enabled — which would take the whole stack down on the next restart.
    DEPLOYMENT_MODE: Literal["local", "local-ssl"] = "local"
    BASE_URL: str = "http://localhost"

    # ── Database ─────────────────────────────────────────
    DATABASE_URL: str  # required — no default

    # ── Redis ─────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── Security ──────────────────────────────────────────
    SECRET_KEY: str  # required — no default
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Set True in production when serving over HTTPS so the refresh-token
    # cookie gets the Secure flag and cannot be sent over plain HTTP.
    COOKIE_SECURE: bool = False

    # ── MinIO ─────────────────────────────────────────────
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str  # required — no default; treat as a password
    MINIO_BUCKET_ATTENDANCE: str = "attendance-proofs"
    MINIO_SECURE: bool = False

    # ── WhatsApp (Meta Cloud API) ─────────────────────────
    # Primary config is the DB (Admin → Settings → Notifications); these are env fallbacks.
    WHATSAPP_TOKEN: str = ""              # Cloud API access token
    WHATSAPP_PHONE_NUMBER_ID: str = ""    # Meta "Phone number ID"
    WHATSAPP_TEMPLATE: str = ""           # approved template name (body has one {{1}} param)
    WHATSAPP_LANGUAGE: str = "en_US"      # template language code
    WHATSAPP_API_VERSION: str = "v21.0"   # graph.facebook.com API version

    # ── SMTP ─────────────────────────────────────────────
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@attendance.local"
    SMTP_TLS: bool = True

    # ── Face recognition ─────────────────────────────────
    FACE_CONFIDENCE_THRESHOLD: float = 0.95
    FACE_COOLDOWN_SECONDS: int = 300
    FRAME_SKIP: int = 3

    # ── Attendance engine ─────────────────────────────────
    # Cooldown: reject duplicate events of the same type within this window.
    # Matches the face-service cooldown (300 s = 5 min) so both layers agree.
    ATTENDANCE_COOLDOWN_SECONDS: int = 300

    # ── Self-service selfie check-in ──────────────────────
    # Comma-separated CIDRs treated as "the office network" for the LAN gate.
    # Empty → any private/loopback address (RFC1918) counts as on-LAN, which
    # suits the default single-PC LAN install. The gate is flag-and-audit only:
    # off-LAN check-ins are still recorded, just flagged in the audit log.
    SELFIE_ALLOWED_SUBNETS: str = ""
    # Face-service URL for the /verify-selfie liveness+embedding call.
    FACE_SERVICE_URL: str = "http://face-recognition:8001"

    # ── Biometric ─────────────────────────────────────────
    BIOMETRIC_CHECKIN_STATE: int = 0
    # When True, the unauthenticated /attendance/biometric-event webhook only
    # accepts payloads whose device serial ("sn") matches a registered device.
    # Recommended in production as defence-in-depth alongside network isolation.
    BIOMETRIC_REQUIRE_REGISTERED_DEVICE: bool = False

    # ── Payroll defaults ──────────────────────────────────
    # Legacy per-late model (kept for back-compat; superseded by the % model below).
    DEFAULT_ALLOWED_LATE_COUNT: int = 3
    DEFAULT_LATE_PENALTY_PAISE: int = 20000  # ₹200 stored as paise
    # Percentage-of-a-day late-penalty model (all editable in the admin portal):
    #   every N late days = one penalty unit; each unit costs P% of a day's salary;
    #   the first G grace-days of penalty are forgiven; a day's salary = monthly / D.
    DEFAULT_LATE_DAYS_PER_UNIT: int = 3
    DEFAULT_PENALTY_PERCENT_PER_UNIT: int = 50
    DEFAULT_GRACE_DAYS: float = 1.5
    DEFAULT_SALARY_DAYS_PER_MONTH: int = 30

    # ── Attendance defaults ───────────────────────────────
    # Org-wide grace period (minutes after office start before a check-in is late),
    # used when a branch does not set its own grace override. Overridable in the admin
    # portal via system_policies['attendance.grace_period_minutes'].
    DEFAULT_GRACE_PERIOD_MINUTES: int = 15

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def ensure_async_driver(cls, v: str) -> str:
        """Coerce plain postgresql:// → postgresql+asyncpg:// so SQLAlchemy always uses the async engine."""
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

# asyncpg server_settings enforces UTC at the connection level for every session.
# Defined here — not in database.py — so alembic/env.py can import it without
# triggering engine creation as a side effect.
ASYNCPG_CONNECT_ARGS: dict = {
    "server_settings": {"timezone": "UTC"},
}
