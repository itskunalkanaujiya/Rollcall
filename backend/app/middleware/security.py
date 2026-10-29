"""Cross-site request protection and security headers."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests whose Origin header names a site we do not trust.

    Authentication uses a SameSite cookie; this is a second layer against CSRF. Requests without
    an Origin header (curl, server-to-server, tests) are allowed - those cannot ride a browser cookie."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method in UNSAFE:
            origin = request.headers.get("origin")
            if origin and origin not in get_settings().cors_origin_list:
                return JSONResponse({"error": {"code": "bad_origin", "message": "Origin not allowed",
                                               "details": None}}, status_code=403)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")   # never cache personal data
        return resp
