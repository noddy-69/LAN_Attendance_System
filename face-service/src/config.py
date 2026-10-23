"""Face-recognition service configuration loaded from .env / environment."""
import os


def _bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes")


def _int(key: str, default: int) -> int:
    v = os.environ.get(key)
    return int(v) if v is not None else default


def _float(key: str, default: float) -> float:
    v = os.environ.get(key)
    return float(v) if v is not None else default


def _str(key: str, default: str) -> str:
    v = os.environ.get(key)
    return v if v is not None else default


class _Settings:
    # ── Camera streams (CP Plus RTSP) ─────────────────────────────────────────
    ENTRY_CAMERA_URL: str    = _str("ENTRY_CAMERA_URL", "")
    EXIT_CAMERA_URL: str     = _str("EXIT_CAMERA_URL", "")
    CAMERA_FPS: int          = _int("CAMERA_FPS", 5)
    FRAME_SKIP: int          = _int("FRAME_SKIP", 5)
    CAMERA_RECONNECT_S: float = _float("CAMERA_RECONNECT_S", 30.0)

    # ── Tracking ──────────────────────────────────────────────────────────────
    TRACK_THRESH: float      = _float("TRACK_THRESH", 0.5)
    LOW_THRESH: float        = _float("LOW_THRESH", 0.1)
    NEW_TRACK_THRESH: float  = _float("NEW_TRACK_THRESH", 0.6)
    TRACK_BUFFER: int        = _int("TRACK_BUFFER", 30)
    MATCH_THRESH: float      = _float("MATCH_THRESH", 0.8)

    # ── Face recognition ──────────────────────────────────────────────────────
    FACE_CONFIDENCE_THRESHOLD: float = _float("FACE_CONFIDENCE_THRESHOLD", 0.95)
    FACE_COOLDOWN_SECONDS: int       = _int("FACE_COOLDOWN_SECONDS", 300)
    MODEL_PACK: str                  = _str("MODEL_PACK", "buffalo_sc")
    DET_SIZE: int                    = _int("DET_SIZE", 320)
    EMBED_REFRESH_SECONDS: int       = _int("EMBED_REFRESH_SECONDS", 300)

    # ── Anti-spoofing (liveness) ───────────────────────────────────────────────
    # Disabled by default. When enabled, drop MiniFASNet ONNX model(s) into
    # FACE_ANTISPOOF_MODEL_DIR. Rejects printed-photo / screen-replay attacks.
    FACE_ANTISPOOF_ENABLED: bool     = _bool("FACE_ANTISPOOF_ENABLED", False)
    FACE_ANTISPOOF_MODEL_DIR: str    = _str("FACE_ANTISPOOF_MODEL_DIR", "/opt/insightface/antispoof")
    # Minimum "real" score (0-1) to accept a face. LOW = lenient: the face is treated
    # as real unless the model is confident it is a spoof. 0.2 blocks obvious printed
    # photos / screen replays without false-rejecting genuine phone selfies.
    FACE_ANTISPOOF_THRESHOLD: float  = _float("FACE_ANTISPOOF_THRESHOLD", 0.2)
    # Self-service selfie check-in: passive MiniFASNet anti-spoofing is OFF by default.
    # The bundled models misclassify genuine phone selfies (a live face scored ~0.02
    # "real" in testing), so the layer would lock real staff out. Active head-movement
    # liveness + the backend's 1:1 self-match are the primary guards. A site can enable
    # it (SELFIE_ANTISPOOF_ENABLED=true, made lenient via FACE_ANTISPOOF_THRESHOLD) only
    # after validating the model on its own cameras/lighting.
    SELFIE_ANTISPOOF_ENABLED: bool   = _bool("SELFIE_ANTISPOOF_ENABLED", False)

    # ── Device heartbeat ───────────────────────────────────────────────────────
    # Register the cameras in the Admin portal, then set these to the camera
    # device UUIDs so the dashboard shows them as "live" while streams are up.
    ENTRY_CAMERA_DEVICE_ID: str  = _str("ENTRY_CAMERA_DEVICE_ID", "")
    EXIT_CAMERA_DEVICE_ID: str   = _str("EXIT_CAMERA_DEVICE_ID", "")
    HEARTBEAT_INTERVAL_S: int    = _int("HEARTBEAT_INTERVAL_S", 60)

    # ── Backend API ───────────────────────────────────────────────────────────
    BACKEND_URL: str             = _str("BACKEND_URL", "http://backend:8000")
    FACE_SERVICE_KEY: str        = _str("FACE_SERVICE_KEY", "")
    SERVICE_ACCOUNT_EMAIL: str   = _str("SERVICE_ACCOUNT_EMAIL", "")
    SERVICE_ACCOUNT_PASSWORD: str = _str("SERVICE_ACCOUNT_PASSWORD", "")
    MOCK_BACKEND: bool           = _bool("MOCK_BACKEND", False)
    BRANCH_ID: str               = _str("BRANCH_ID", "")

    # ── MinIO ─────────────────────────────────────────────────────────────────
    MINIO_ENDPOINT: str   = _str("MINIO_ENDPOINT", "minio:9000")
    MINIO_ACCESS_KEY: str = _str("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY: str = _str("MINIO_SECRET_KEY", "")
    MINIO_BUCKET: str     = _str("MINIO_BUCKET", "attendance-proofs")
    MINIO_SECURE: bool    = _bool("MINIO_SECURE", False)


settings = _Settings()
