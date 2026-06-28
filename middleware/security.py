from typing import Type, Set
"""
Security headers middleware for RoadSoS.

Adds standard HTTP security headers to every response.
These protect against common web vulnerabilities:

- X-Content-Type-Options: nosniff
    Prevents browsers from MIME-sniffing the response content type.
    Stops certain XSS attacks via crafted content.

- X-Frame-Options: DENY
    Prevents the app from being embedded in an iframe.
    Blocks clickjacking attacks.

- X-XSS-Protection: 1; mode=block
    Legacy XSS filter hint for older browsers.

- Strict-Transport-Security: max-age=31536000; includeSubDomains
    Forces HTTPS for one year. Railway serves everything over HTTPS
    so this is always safe to set.

- Content-Security-Policy: default-src 'self'
    Restricts what resources can be loaded. Set to 'self' because
    this is a pure API (no frontend served from here).

- Referrer-Policy: strict-origin-when-cross-origin
    Controls Referer header — limits info leakage on cross-origin calls.

- Cache-Control: no-store
    Prevents caching of API responses by proxies/browsers by default.
    Individual endpoints can override this if needed (e.g., /health).

- X-RoadSoS-Version: 2.0.0
    Custom header so clients can verify they're talking to the right API.
    Use the VERSION value from config.py.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to every outgoing HTTP response.

    Implemented as Starlette BaseHTTPMiddleware so it works with
    FastAPI's ASGI stack. FastAPI's add_middleware() call registers
    it correctly.

    Usage in main.py:
        from middleware.security import SecurityHeadersMiddleware
        app.add_middleware(SecurityHeadersMiddleware)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"]  = "nosniff"
        response.headers["X-Frame-Options"]          = "DENY"
        response.headers["X-XSS-Protection"]         = "1; mode=block"
        response.headers["Referrer-Policy"]           = (
            "strict-origin-when-cross-origin"
        )
        response.headers["Content-Security-Policy"]   = "default-src 'self'"
        response.headers["Cache-Control"]             = "no-store"
        response.headers["X-RoadSoS-Version"]         = getattr(settings, "VERSION", settings.APP_VERSION)

        # Only add HSTS in production (when ENVIRONMENT != "development")
        # Avoids breaking local HTTP dev server
        if getattr(settings, "ENVIRONMENT", "development") != "development":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
