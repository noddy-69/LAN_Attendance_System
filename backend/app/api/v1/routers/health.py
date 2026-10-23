"""
Health endpoint
===============
Returns liveness + dependency probes.  Used by Docker healthcheck and
any external monitoring.

Response shape:
  { "status": "ok"|"degraded", "db": "ok"|"error", "redis": "ok"|"error" }

Redis ping uses a raw TCP connection (no redis client package required).
"""
import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

# No prefix — mounted at /api/v1/health by the parent router
router = APIRouter(tags=["health"])


async def _db_ok(db: AsyncSession) -> bool:
    try:
        await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _redis_ok() -> bool:
    """Ping Redis using raw RESP protocol — no redis client package needed."""
    parsed = urlparse(settings.REDIS_URL)
    host = parsed.hostname or "redis"
    port = parsed.port or 6379
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=2.0
        )
        writer.write(b"*1\r\n$4\r\nPING\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return response.strip() == b"+PONG"
    except Exception:
        return False


@router.api_route("/health", methods=["GET", "HEAD"])
async def health(db: AsyncSession = Depends(get_db)):
    """
    Liveness + dependency probe.
    Returns HTTP 200 if all checks pass, HTTP 503 if any dependency is down.
    """
    db_status = await _db_ok(db)
    redis_status = await _redis_ok()

    all_ok = db_status and redis_status
    body = {
        "status": "ok" if all_ok else "degraded",
        "db": "ok" if db_status else "error",
        "redis": "ok" if redis_status else "error",
    }
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content=body,
    )
