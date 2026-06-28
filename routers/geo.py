from fastapi import APIRouter, Depends, HTTPException, Query
from database import get_db
from schemas.geo import (
    ReverseGeocodeResponse, GeoSearchResponse, GeoSearchResult
)
from services.geocoding import (
    make_geo_cache_key, get_geo_cache, save_geo_cache,
    google_reverse_geocode, google_forward_geocode,
    nominatim_reverse_geocode, nominatim_forward_geocode
)
from schemas.location import get_state_code, is_within_coverage
from utils.logger import get_logger
from typing import Annotated

router = APIRouter(tags=["Geocoding"])
logger = get_logger(__name__)


# ── Endpoint 1: GET /geo/reverse ──────────────────────────────

@router.get("/geo/reverse", response_model=ReverseGeocodeResponse)
async def reverse_geocode(
    lat: Annotated[float, Query(..., ge=-90, le=90)],
    lng: Annotated[float, Query(..., ge=-180, le=180)],
    db=Depends(get_db)
):
    """
    Convert GPS coordinates to human-readable address.
    Used by frontend to show "Your location: NH44, Panipat" instead
    of raw coordinates.

    Fallback chain:
      1. SQLite cache (fastest — skip API calls if already resolved)
      2. Google Geocoding API (accurate, structured)
      3. Nominatim/OSM (free, no key, slightly less accurate)
      4. Coordinate-based fallback (last resort — uses bounds detection)

    Never returns 404 — always returns something, even if just
    coordinates with detected state from bounding box.
    """

    # Step 1: Check cache (round to 3dp for key)
    cache_key = make_geo_cache_key(
        "reverse",
        f"{round(lat, 3)}:{round(lng, 3)}"
    )
    cached = await get_geo_cache(db, cache_key)
    if cached:
        logger.debug(f"Reverse geocode cache hit: ({lat}, {lng})")
        return ReverseGeocodeResponse(
            lat=lat, lng=lng,
            data_source="cache",
            **{k: v for k, v in cached.items()
               if k != "data_source"}
        )

    # Step 2: Try Google Geocoding
    result = await google_reverse_geocode(lat, lng)
    data_source = "google"

    # Step 3: Fallback to Nominatim
    if not result:
        logger.info(
            f"Google geocoding unavailable, trying Nominatim "
            f"for ({lat}, {lng})"
        )
        result = await nominatim_reverse_geocode(lat, lng)
        data_source = "nominatim"

    # Step 4: Last resort — coordinate-based detection only
    if not result:
        logger.warning(
            f"All geocoding sources failed for ({lat}, {lng}), "
            f"using coordinate fallback"
        )
        state_code = get_state_code(lat, lng)
        state_name = None
        if state_code == "HR":
            state_name = "Haryana"
        elif state_code == "DL":
            state_name = "Delhi"

        return ReverseGeocodeResponse(
            lat=lat,
            lng=lng,
            address=f"Location at {lat:.4f}°N, {lng:.4f}°E",
            pincode=None,
            city=None,
            district=None,
            state=state_name,
            state_code=state_code,
            country="IN",
            data_source="fallback"
        )

    # Save to cache
    state_code = result.get("state_code") or get_state_code(lat, lng)
    save_geo_cache(db, cache_key, result, state_code or "HR")

    return ReverseGeocodeResponse(
        lat=lat,
        lng=lng,
        data_source=data_source,
        address=result.get("address", ""),
        pincode=result.get("pincode"),
        city=result.get("city"),
        district=result.get("district"),
        state=result.get("state"),
        state_code=result.get("state_code"),
        country=result.get("country", "IN")
    )


# ── Endpoint 2: GET /geo/search ───────────────────────────────

@router.get("/geo/search", response_model=GeoSearchResponse)
async def forward_geocode(
    q: Annotated[str, Query(..., min_length=2, max_length=200,
                            description="Location search query")],
    lang: str = Query(default="en"),
    limit: int = Query(default=5, ge=1, le=10),
    db=Depends(get_db)
):
    """
    Forward geocoding — convert a text query to coordinates.
    Used when user types location instead of sharing GPS.

    Examples:
      q="NH44 Panipat Toll"  → coordinates near Panipat toll
      q="AIIMS Delhi"         → AIIMS Delhi coordinates
      q="Rohtak civil hospital" → civil hospital coordinates

    Fallback chain:
      1. SQLite cache
      2. Google Geocoding API
      3. Nominatim

    Returns list of results sorted by relevance (Google/Nominatim order).
    Each result has within_coverage flag (True if in HR/DL bounds).
    Never returns 404 — returns empty results list if nothing found.
    """

    # Step 1: Check cache
    cache_key = make_geo_cache_key("search", q)
    cached = await get_geo_cache(db, cache_key)
    if cached:
        results_data = cached.get("results", [])
        return GeoSearchResponse(
            query=q,
            results=[GeoSearchResult(
                within_coverage=is_within_coverage(r["lat"], r["lng"]),
                **{k: v for k, v in r.items()
                   if k in GeoSearchResult.model_fields and k != "within_coverage"}
            ) for r in results_data],
            data_source="cache"
        )

    # Step 2: Try Google
    raw_results = await google_forward_geocode(q, limit)
    data_source = "google"

    # Step 3: Fallback to Nominatim
    if not raw_results:
        logger.info(
            f"Google forward geocoding unavailable, "
            f"trying Nominatim for '{q}'"
        )
        raw_results = await nominatim_forward_geocode(q, limit)
        data_source = "nominatim"

    # No results from either source
    if not raw_results:
        logger.warning(f"No geocoding results for query: '{q}'")
        return GeoSearchResponse(
            query=q,
            results=[],
            data_source="none"
        )

    # Build response + add within_coverage flag
    results = []
    for r in raw_results:
        within = is_within_coverage(r["lat"], r["lng"])
        results.append(GeoSearchResult(
            address=r.get("address", ""),
            lat=r["lat"],
            lng=r["lng"],
            place_id=r.get("place_id"),
            pincode=r.get("pincode"),
            city=r.get("city"),
            state=r.get("state"),
            state_code=r.get("state_code"),
            within_coverage=within
        ))

    # Sort: within_coverage=True results first
    results.sort(key=lambda x: (not x.within_coverage))

    # Cache the results
    state_code = results[0].state_code if results else "HR"
    save_geo_cache(
        db, cache_key,
        {"results": [r.model_dump() for r in results]},
        state_code or "HR"
    )

    return GeoSearchResponse(
        query=q,
        results=results,
        data_source=data_source
    )
