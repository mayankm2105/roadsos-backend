from fastapi import APIRouter
from fastapi import Request as FastAPIRequest
from datetime import datetime, timezone

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(request: FastAPIRequest):
    """
    Comprehensive health check.

    Returns overall status ("ok" | "degraded" | "error") plus
    per-service status for every dependency.

    Reads startup check results from app.state.preflight_results.
    Also does a live SQLite count check on every call to catch
    issues that developed after startup.

    Response shape:
    {
      "status": "ok",              // "ok" = all critical services up
                                   // "degraded" = non-critical failures
                                   // "error" = critical service down
      "version": "2.0.0",
      "region_coverage": ["HR", "DL"],
      "environment": "production",
      "services": {
        "sqlite":         "ok (1247 cache entries)",
        "gemini_api":     "ok",
        "google_places":  "ok",
        "whisper_stt":    "ok (model=base)",
        "rate_limiter":   "ok"
      },
      "api_keys": {
        "GEMINI_API_KEY":          "set",
        "GOOGLE_PLACES_API_KEY":   "set",
        "GOOGLE_GEOCODING_API_KEY": "set",
        "ADMIN_KEY":               "set",
        "SOS_BASE_URL":            "set"
      },
      "timestamp": "2026-06-26T10:30:00Z"
    }

    Status logic:
    - "ok"       → sqlite + gemini_api both working
    - "degraded" → sqlite ok but one of Google APIs failing
    - "error"    → sqlite failing (core functionality broken)

    This endpoint is hit by Railway every 30 seconds as a health check.
    Keep it fast (<500ms). Do NOT make external API calls here —
    read from preflight results only.
    """
    from config import settings
    from database import SessionLocal
    from models.cache import CacheEntry

    # Get pre-flight results stored during startup
    preflight = getattr(request.app.state, "preflight_results", {})

    # Live SQLite check (fast — just a COUNT query)
    try:
        db = SessionLocal()
        count = db.query(CacheEntry).count()
        db.close()
        sqlite_status = f"ok ({count} cache entries)"
    except Exception as e:
        sqlite_status = f"error: {str(e)}"

    services = {
        "sqlite":        sqlite_status,
        "gemini_api":    preflight.get("gemini", "unknown"),
        "google_places": preflight.get("google_places", "unknown"),
        "whisper_stt":   preflight.get("whisper", "unknown"),
        "rate_limiter":  "ok"
    }

    # Determine overall status
    if "error" in services["sqlite"]:
        overall = "error"
    elif any(
        "error" in str(v)
        for k, v in services.items()
        if k in ["gemini_api", "google_places"]
    ):
        overall = "degraded"
    else:
        overall = "ok"

    return {
        "status": overall,
        "version": settings.VERSION,
        "region_coverage": ["HR", "DL"],
        "environment": settings.ENVIRONMENT,
        "services": services,
        "api_keys": preflight.get("api_keys", {}),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
