import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Any
import httpx
from config import settings
from utils.logger import get_logger
from schemas.location import get_state_code, HARYANA_BOUNDS, DELHI_BOUNDS

logger = get_logger(__name__)

# ── Cache helpers ─────────────────────────────────────────────

def make_geo_cache_key(operation: str, value: str) -> str:
    """
    Build a unique cache key for geocoding results.

    For reverse geocoding: round lat/lng to 3 decimal places
    (~111m precision) so nearby coordinates share cache entries.
    operation="reverse", value="28.614:77.209"

    For forward geocoding: lowercase + strip the query string.
    operation="search", value="nh44 panipat toll"

    Hash long keys to stay under 200 char SQLite limit.
    Format: "geo:{operation}:{hash_or_value}"
    """
    clean_value = value.lower().strip()
    if len(clean_value) > 100:
        clean_value = hashlib.md5(clean_value.encode()).hexdigest()
    return f"geo:{operation}:{clean_value}"


async def get_geo_cache(db, cache_key: str) -> Optional[dict]:
    """
    Check SQLite cache for a geocoding result.
    Returns the cached data dict or None if miss/expired.
    Increments hit_count on cache hit.
    """
    from models.cache import CacheEntry
    entry = db.query(CacheEntry).filter(
        CacheEntry.cache_key == cache_key,
        CacheEntry.expires_at > datetime.utcnow()
    ).first()

    if entry:
        # Increment hit count (copy pattern for JSON mutation safety)
        entry.hit_count = (entry.hit_count or 0) + 1
        db.commit()
        logger.debug(f"Geo cache HIT: {cache_key}")
        return entry.data

    return None


def save_geo_cache(db, cache_key: str, data: dict,
                   state_code: str = "HR") -> None:
    """
    Save a geocoding result to SQLite cache.
    TTL: 7 days (geocoding results change very rarely).
    Uses upsert pattern: delete existing + insert new.
    """
    from models.cache import CacheEntry
    try:
        # Delete existing if present
        db.query(CacheEntry).filter(
            CacheEntry.cache_key == cache_key
        ).delete()

        entry = CacheEntry(
            cache_key=cache_key,
            category="geo",
            state_code=state_code,
            data=data,
            data_source="google",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=7),
            version=datetime.utcnow().strftime("%Y%m%d"),
            hit_count=0
        )
        db.add(entry)
        db.commit()
        logger.debug(f"Geo cache SAVED: {cache_key}")
    except Exception as e:
        logger.warning(f"Failed to save geo cache: {e}")
        db.rollback()


# ── State code helpers ────────────────────────────────────────

STATE_NAME_TO_CODE = {
    "haryana": "HR",
    "delhi": "DL",
    "national capital territory of delhi": "DL",
    "nct of delhi": "DL",
}

def extract_state_code_from_name(state_name: str) -> Optional[str]:
    """Convert Google's state name to our 2-letter state code."""
    if not state_name:
        return None
    return STATE_NAME_TO_CODE.get(state_name.lower().strip())


# ── Google Geocoding API ──────────────────────────────────────

GOOGLE_GEOCODING_BASE = "https://maps.googleapis.com/maps/api/geocode/json"

async def google_reverse_geocode(lat: float, lng: float) -> Optional[dict]:
    """
    Call Google Geocoding API to convert coordinates to address.

    API: GET /maps/api/geocode/json?latlng={lat},{lng}&key={key}

    Parse the first result from response["results"][0]:

    Component extraction from address_components array:
    - pincode: type "postal_code" → long_name
    - city: type "locality" → long_name
              fallback: type "administrative_area_level_2" → long_name
    - district: type "administrative_area_level_2" → long_name
    - state: type "administrative_area_level_1" → long_name
    - country: type "country" → short_name (e.g. "IN")

    Full address: result["formatted_address"]

    Returns dict:
    {
      "address": "...",
      "pincode": "132103",
      "city": "Panipat",
      "district": "Panipat",
      "state": "Haryana",
      "state_code": "HR",
      "country": "IN",
      "data_source": "google"
    }

    Returns None on:
    - Missing or empty GOOGLE_GEOCODING_API_KEY
    - ZERO_RESULTS status
    - HTTP error
    - Any exception
    """
    key = settings.GOOGLE_GEOCODING_API_KEY or settings.GOOGLE_PLACES_API_KEY
    if not key:
        logger.warning("GOOGLE_GEOCODING_API_KEY and GOOGLE_PLACES_API_KEY not configured")
        return None

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                GOOGLE_GEOCODING_BASE,
                params={
                    "latlng": f"{lat},{lng}",
                    "key": key,
                    "language": "en",
                    "region": "IN"
                }
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") == "ZERO_RESULTS":
            return None

        if data.get("status") not in ["OK"]:
            logger.warning(
                f"Google Geocoding error: {data.get('status')} "
                f"— {data.get('error_message', '')}"
            )
            return None

        results = data.get("results", [])
        if not results:
            return None

        # Parse first result
        result = results[0]
        components = result.get("address_components", [])

        pincode = city = district = state = None
        country = "IN"

        for comp in components:
            types = comp.get("types", [])
            long_name = comp.get("long_name", "")
            short_name = comp.get("short_name", "")

            if "postal_code" in types:
                pincode = long_name
            elif "locality" in types:
                city = long_name
            elif "administrative_area_level_2" in types:
                district = long_name
                if not city:
                    city = long_name
            elif "administrative_area_level_1" in types:
                state = long_name
            elif "country" in types:
                country = short_name

        state_code = extract_state_code_from_name(state)
        if not state_code:
            # Try coordinate-based detection as fallback
            state_code = get_state_code(lat, lng)

        return {
            "address": result.get("formatted_address", ""),
            "pincode": pincode,
            "city": city,
            "district": district,
            "state": state,
            "state_code": state_code,
            "country": country,
            "data_source": "google"
        }

    except Exception as e:
        logger.warning(f"Google reverse geocoding failed: {e}")
        return None


async def google_forward_geocode(
    query: str,
    limit: int = 5
) -> Optional[list[dict]]:
    """
    Call Google Geocoding API for forward geocoding (text → coordinates).

    API: GET /maps/api/geocode/json?address={query}&key={key}
         &components=country:IN  ← restrict to India

    Parse each result from response["results"]:
    {
      "address": result["formatted_address"],
      "lat": result["geometry"]["location"]["lat"],
      "lng": result["geometry"]["location"]["lng"],
      "place_id": result["place_id"],
      "pincode": extracted from address_components,
      "city": extracted,
      "state": extracted,
      "state_code": extracted
    }

    Returns list of dicts or None on failure.
    Limit results to first `limit` items.
    """
    key = settings.GOOGLE_GEOCODING_API_KEY or settings.GOOGLE_PLACES_API_KEY
    if not key:
        return None

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                GOOGLE_GEOCODING_BASE,
                params={
                    "address": query,
                    "key": key,
                    "language": "en",
                    "region": "IN",
                    "components": "country:IN"
                }
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") not in ["OK"]:
            return None

        results = []
        for item in data.get("results", [])[:limit]:
            components = item.get("address_components", [])
            pincode = city = state = None
            country = "IN"

            for comp in components:
                types = comp.get("types", [])
                if "postal_code" in types:
                    pincode = comp["long_name"]
                elif "locality" in types:
                    city = comp["long_name"]
                elif "administrative_area_level_1" in types:
                    state = comp["long_name"]
                elif "country" in types:
                    country = comp["short_name"]

            location = item["geometry"]["location"]
            state_code = extract_state_code_from_name(state)
            if not state_code:
                state_code = get_state_code(
                    location["lat"], location["lng"]
                )

            results.append({
                "address": item.get("formatted_address", ""),
                "lat": location["lat"],
                "lng": location["lng"],
                "place_id": item.get("place_id"),
                "pincode": pincode,
                "city": city,
                "state": state,
                "state_code": state_code,
                "data_source": "google"
            })

        return results if results else None

    except Exception as e:
        logger.warning(f"Google forward geocoding failed: {e}")
        return None


# ── Nominatim fallback (OpenStreetMap) ───────────────────────

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"

async def nominatim_reverse_geocode(lat: float, lng: float) -> Optional[dict]:
    """
    Nominatim reverse geocoding fallback.
    Uses OpenStreetMap Nominatim API — completely free, no key needed.

    API: GET /reverse?lat={lat}&lon={lng}&format=json&addressdetails=1

    IMPORTANT: Nominatim requires a User-Agent header.
    Use: "RoadSoS-App/2.0 (hackathon project)"
    Without it, requests get blocked.

    Parse response:
    - address: response["display_name"]
    - pincode: response["address"]["postcode"]
    - city: response["address"].get("city")
             or response["address"].get("town")
             or response["address"].get("village")
    - district: response["address"].get("county")
                or response["address"].get("state_district")
    - state: response["address"]["state"]
    - country: response["address"]["country_code"].upper()

    Returns same dict shape as google_reverse_geocode() but
    with data_source="nominatim".

    Returns None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{NOMINATIM_BASE}/reverse",
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "json",
                    "addressdetails": 1
                },
                headers={
                    "User-Agent": "RoadSoS-App/2.0 (hackathon project)",
                    "Accept-Language": "en"
                }
            )
            resp.raise_for_status()
            data = resp.json()

        if "error" in data:
            return None

        addr = data.get("address", {})

        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("municipality")
        )
        district = (
            addr.get("county")
            or addr.get("state_district")
        )
        state = addr.get("state", "")
        state_code = extract_state_code_from_name(state)
        if not state_code:
            state_code = get_state_code(lat, lng)

        return {
            "address": data.get("display_name", ""),
            "pincode": addr.get("postcode"),
            "city": city,
            "district": district,
            "state": state,
            "state_code": state_code,
            "country": addr.get("country_code", "in").upper(),
            "data_source": "nominatim"
        }

    except Exception as e:
        logger.warning(f"Nominatim reverse geocoding failed: {e}")
        return None


async def nominatim_forward_geocode(
    query: str,
    limit: int = 5
) -> Optional[list[dict]]:
    """
    Nominatim forward geocoding fallback.

    API: GET /search?q={query}&format=json&addressdetails=1
                    &countrycodes=in&limit={limit}

    Parse each result:
    {
      "address": result["display_name"],
      "lat": float(result["lat"]),
      "lng": float(result["lon"]),
      "place_id": str(result["place_id"]),
      "pincode": result["address"].get("postcode"),
      "city": result["address"].get("city") or .get("town"),
      "state": result["address"].get("state"),
      "state_code": extracted
    }

    Returns list of dicts or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{NOMINATIM_BASE}/search",
                params={
                    "q": query,
                    "format": "json",
                    "addressdetails": 1,
                    "countrycodes": "in",
                    "limit": limit
                },
                headers={
                    "User-Agent": "RoadSoS-App/2.0 (hackathon project)",
                    "Accept-Language": "en"
                }
            )
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return None

        results = []
        for item in data:
            addr = item.get("address", {})
            lat = float(item["lat"])
            lng = float(item["lon"])
            state = addr.get("state", "")
            state_code = extract_state_code_from_name(state)
            if not state_code:
                state_code = get_state_code(lat, lng)

            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
            )

            results.append({
                "address": item.get("display_name", ""),
                "lat": lat,
                "lng": lng,
                "place_id": str(item.get("place_id", "")),
                "pincode": addr.get("postcode"),
                "city": city,
                "state": state,
                "state_code": state_code,
                "data_source": "nominatim"
            })

        return results if results else None

    except Exception as e:
        logger.warning(f"Nominatim forward geocoding failed: {e}")
        return None
