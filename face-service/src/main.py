"""
Face Recognition Service — application entry point.

Startup sequence:
  1. Load InsightFace buffalo_sc model
  2. Fetch known face embeddings from backend
  3. Connect to MinIO
  4. Start camera threads (one per configured ENTRY / EXIT camera URL)
  5. Serve the FastAPI router on port 8001

All config via src/config.py (reads from .env or environment variables).
"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from src.config import settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # ── Start-up ──────────────────────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("Face recognition service starting up")
    log.info("Backend URL : %s", settings.BACKEND_URL)
    log.info("Entry camera: %s", settings.ENTRY_CAMERA_URL or "(none)")
    log.info("Exit camera : %s", settings.EXIT_CAMERA_URL or "(none)")
    log.info("Mock backend: %s", settings.MOCK_BACKEND)

    try:
        from src.recognizer import FaceRecognizer
        from src.engine import AttendanceEngine

        recognizer = FaceRecognizer()
        recognizer.initialize()          # loads model, embeddings, MinIO
        app.state.recognizer = recognizer

        engine = AttendanceEngine(recognizer)
        engine.start()                   # launches daemon camera threads
        app.state.engine = engine

        log.info("Face recognition service ready")
    except ImportError as exc:
        log.warning(
            "Face recognition ML packages not available (%s). "
            "Service will start in degraded mode — API endpoints will return 503 "
            "until packages are installed and the service is restarted.",
            exc,
        )
        app.state.recognizer = None
        app.state.engine = None
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("Face recognition service shutting down")
    if app.state.engine is not None:
        app.state.engine.stop()


app = FastAPI(
    title="Face Recognition Service",
    version="1.0.0",
    docs_url="/docs",
    lifespan=_lifespan,
)

from src.api import router as _api_router  # noqa: E402
app.include_router(_api_router)
