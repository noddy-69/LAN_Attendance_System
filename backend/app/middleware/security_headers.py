from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# These headers protect direct backend access (e.g. internal tooling, dev mode,
# curl against port 8000).  In production they are ALSO set by Nginx on every
# proxied response, so we use setdefault — if the header already exists we leave
# it alone, preventing duplicates when the proxy forwards the response.
_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:;"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in _HEADERS.items():
            # setdefault: only adds the header when it is not already present.
            # When Nginx runs in front of us it strips our values and re-injects
            # its own via add_header, so the client always sees exactly one copy.
            if header.lower() not in (k.lower() for k in response.headers.keys()):
                response.headers[header] = value
        return response
