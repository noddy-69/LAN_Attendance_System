from contextlib import asynccontextmanager

import starlette.exceptions as starlette_exc
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.middleware.audit import RequestLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Import all ORM models so SQLAlchemy resolves every relationship before
    # the first request.  The import is idempotent (cached by Python's module system).
    import app.models  # noqa: F401
    # Ensure MinIO bucket exists and avatars/ prefix is public-readable.
    from app.services.storage_service import init_bucket
    await init_bucket()
    yield
    await engine.dispose()


app = FastAPI(
    title="Attendance & Workforce Management API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# In local deployment everything is behind Nginx on port 80 (same origin), so
# CORS is technically not required.  We configure it anyway so the Next.js dev
# server (port 3000) and any curl/Postman client can reach the API directly.
_cors_origins: list[str] = list(
    {  # set deduplicates if BASE_URL repeats a localhost variant
        settings.BASE_URL,
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
    }
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,  # required: refresh token lives in an HttpOnly cookie
    allow_methods=["*"],
    allow_headers=["*"],
)
# Logging is outermost so it captures total wall-clock time including CORS processing.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


# ── Exception handlers ────────────────────────────────────────────────────────
# All handlers return the same ApiResponse envelope so clients never see
# two different error shapes from this service.

def _error_response(status_code: int, detail: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "data": None, "error": detail},
        headers=headers,
    )


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    """Handles all our custom application exceptions (UnauthorizedError, etc.)."""
    return _error_response(exc.status_code, exc.detail, getattr(exc, "headers", None))


@app.exception_handler(starlette_exc.HTTPException)
async def http_exception_handler(_: Request, exc: starlette_exc.HTTPException) -> JSONResponse:
    """
    Catches FastAPI/Starlette's own HTTP exceptions (404 route not found,
    405 method not allowed, etc.) so they also use the ApiResponse envelope
    instead of the default {"detail": "..."} shape.
    """
    return _error_response(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Flatten Pydantic v2 validation errors into a single readable string."""
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = " → ".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = first.get("msg", "Validation error")
        detail = f"{loc}: {msg}" if loc else msg
    else:
        detail = "Request validation failed"
    return _error_response(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all for truly unexpected errors.
    Stack trace is logged server-side; the client only sees a generic message
    so internal details are never leaked.
    """
    import logging
    logging.getLogger(__name__).exception("Unhandled server error: %s", exc)
    return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error")


# ── Routers ───────────────────────────────────────────────────────────────────
from app.api.v1.router import api_router  # noqa: E402 — must come after app creation

app.include_router(api_router)
