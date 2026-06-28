import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Annotated, Optional
from database import get_db
from schemas.offline import (
    OfflineCacheResponse, CacheRegion,
    CacheLastUpdatedResponse, StateVersionInfo,
    CacheSyncRequest, CacheSyncResponse
)
from services.cache_manager import (
    get_cache_for_state, get_cache_version_info,
    bump_cache_version, PINCODE_COUNTS, SERVICE_CATEGORIES
)
from config import settings
from utils.logger import get_logger

router = APIRouter(tags=["Offline Cache"])
logger = get_logger(__name__)

VALID_STATES = ["HR", "DL"]


# ── Endpoint 1: GET /offline/cache ───────────────────────────

@router.get("/offline/cache", response_model=OfflineCacheResponse)
async def get_offline_cache(
    state: Annotated[str, Query(
        ...,
        description="State code: HR (Haryana) or DL (Delhi)"
    )],
    pincode: Optional[str] = Query(
        default=None,
        description="Filter by specific 6-digit pincode"
    ),
    format: str = Query(
        default="json",
        description="Response format: 'json' only (sqlite not supported in this version)"
    ),
    db=Depends(get_db)
):
    """
    Download the full offline service cache for a state.
    Called by the PWA service worker on first load and on cache refresh.

    Logic:
    1. Validate state is in ["HR", "DL"] → return 400 if not
    2. If format == "sqlite": return 400 with message
       "SQLite format not supported. Use format=json."
       (SQLite binary download is out of scope for hackathon)
    3. Call get_cache_for_state(db, state, pincode) → grouped dict
    4. Compute total entries_count: sum of all category list lengths
    5. Get version info: call get_cache_version_info(db)[state]
       → last_updated and version
    6. Compute total_pincodes from PINCODE_COUNTS[state] if no pincode
       filter, else 1
    7. Return OfflineCacheResponse

    On empty cache (all category lists are empty):
    - Still return 200 with empty data dict and entries_count: 0
    - Do NOT return 404 or 503
    - Log a warning: "Cache empty for state {state} — Phase 2 data
      may not have been loaded yet"
    """
    state = state.upper().strip()

    if state not in VALID_STATES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_STATE",
                    "message": f"State must be one of {VALID_STATES}. Got: '{state}'."
                }
            }
        )

    if format.lower() == "sqlite":
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "FORMAT_NOT_SUPPORTED",
                    "message": "SQLite format not supported. Use format=json."
                }
            }
        )

    grouped = get_cache_for_state(db, state, pincode)
    entries_count = sum(len(v) for v in grouped.values())

    if entries_count == 0:
        logger.warning(
            f"Cache empty for state {state} — Phase 2 data may not "
            f"have been loaded yet"
        )

    version_info = get_cache_version_info(db)
    state_meta = version_info.get(state, {})
    last_updated = state_meta.get("last_updated")
    total_pincodes = 1 if pincode else PINCODE_COUNTS.get(state, 0)

    return OfflineCacheResponse(
        region=CacheRegion(country="IN", state=state),
        total_pincodes=total_pincodes,
        last_updated=last_updated,
        entries_count=entries_count,
        data=grouped
    )


# ── Endpoint 2: GET /offline/cache/last-updated ───────────────

@router.get("/offline/cache/last-updated",
            response_model=CacheLastUpdatedResponse)
async def cache_last_updated(db=Depends(get_db)):
    """
    Lightweight cache freshness check for PWA service worker.
    PWA should poll this on startup and compare version strings.
    If version has changed, trigger a full /offline/cache download.

    Logic:
    1. Call get_cache_version_info(db) → dict for HR and DL
    2. Build CacheLastUpdatedResponse.states with StateVersionInfo
       for each state
    3. Always returns 200 — never errors
    """
    version_info = get_cache_version_info(db)

    states = {}
    for state_code in ["HR", "DL"]:
        meta = version_info.get(state_code, {})
        states[state_code] = StateVersionInfo(
            last_updated=meta.get("last_updated"),
            version=meta.get("version", "20260614"),
            entries_count=meta.get("entries_count", 0)
        )

    return CacheLastUpdatedResponse(country="IN", states=states)


# ── Endpoint 3: POST /offline/cache/sync (Admin only) ─────────

@router.post("/offline/cache/sync",
             response_model=CacheSyncResponse,
             status_code=202)
async def sync_cache(
    body: CacheSyncRequest,
    db=Depends(get_db)
):
    """
    Admin-only endpoint to trigger a cache refresh.
    For the hackathon, this is a stub — it bumps the version timestamp
    on existing entries rather than re-scraping Google Places.

    Logic:
    1. Validate admin_key == settings.ADMIN_KEY
       → return 401 if mismatch with:
         {"error": {"code": "UNAUTHORIZED", "message": "Invalid admin key"}}
    2. Validate each state in body.states is in ["HR", "DL"]
       → return 400 for invalid states
    3. Call bump_cache_version(db, body.states)
    4. Generate a random job_id (uuid4)
    5. Return 202 CacheSyncResponse

    Note: Real re-scraping (Google Places + Overpass) is out of scope.
    The bump_cache_version stub is sufficient for judge demonstration.
    """
    if body.admin_key != settings.ADMIN_KEY:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Invalid admin key."
                }
            }
        )

    invalid_states = [s for s in body.states if s.upper() not in VALID_STATES]
    if invalid_states:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_STATE",
                    "message": f"Invalid states: {invalid_states}. Use HR or DL."
                }
            }
        )

    states = [s.upper() for s in body.states]
    bump_cache_version(db, states)
    job_id = str(uuid.uuid4())

    logger.info(f"Cache sync triggered by admin. job_id={job_id}, states={states}")

    return CacheSyncResponse(
        job_id=job_id,
        status="queued",
        states=states,
        message=f"Cache version bumped for {states}. "
                f"Full re-scrape not available in hackathon build."
    )
