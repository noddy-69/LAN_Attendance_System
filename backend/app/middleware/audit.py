import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Paths that produce too much noise in the access log.
_SKIP_LOG = {"/api/v1/health", "/api/docs", "/api/redoc", "/api/openapi.json"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Lightweight structured access log for every API call.
    Writes: method path status latency_ms [request_id if present]
    Full audit trail (who changed what) is written inside service-layer functions.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_LOG:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000)

        logger.info(
            "%s %s %d %dms",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
        )
        return response
