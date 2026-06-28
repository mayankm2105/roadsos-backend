"""
Rate limiting middleware for RoadSoS.
Uses slowapi which wraps the `limits` library.

Rate limits chosen for hackathon scale:
- General endpoints:  60 requests/minute per IP
- Chat endpoints:     20 requests/minute per IP  (Gemini has its own quota)
- Voice endpoint:     10 requests/minute per IP  (Whisper is CPU-heavy)
- SOS create:         5  requests/minute per IP  (abuse prevention)
- Triage endpoints:   30 requests/minute per IP

All limits are per-IP (X-Forwarded-For aware for Railway proxy).
On limit exceeded: returns HTTP 429 with a clear JSON error body.
"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse


def get_client_ip(request: Request) -> str:
    """
    Extract real client IP, accounting for Railway's reverse proxy.
    Railway sets X-Forwarded-For. Use the leftmost IP in that header
    (the original client). Fall back to direct connection IP.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request)


# Create the global limiter instance
# key_func: how to identify a "client" (by IP address)
# default_limits: applied to every route unless overridden per-route
limiter = Limiter(
    key_func=get_client_ip,
    default_limits=["60/minute"]
)


async def rate_limit_exceeded_handler(
    request: Request,
    exc: RateLimitExceeded
) -> JSONResponse:
    """
    Custom 429 response body.
    Replaces slowapi's default plain-text response with our standard
    JSON error schema so the frontend can handle it uniformly.

    Response shape:
    {
      "error": {
        "code": "RATE_LIMITED",
        "message": "Too many requests. Please wait before trying again.",
        "retry_after": "60 seconds"
      }
    }
    HTTP 429 with Retry-After header set.
    """
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMITED",
                "message": "Too many requests. Please wait before trying again.",
                "retry_after": str(exc.detail)
            }
        },
        headers={"Retry-After": "60"}
    )


# Per-endpoint limit strings to import into routers
LIMIT_GENERAL = "60/minute"
LIMIT_CHAT    = "20/minute"
LIMIT_VOICE   = "10/minute"
LIMIT_SOS     = "5/minute"
LIMIT_TRIAGE  = "30/minute"
