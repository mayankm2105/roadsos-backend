import json
from pathlib import Path
from typing import Tuple, List, Dict, Any
from sqlalchemy.orm import Session
from services import google_places, overpass, cache_service
from schemas.services import ServiceResult, HospitalResult, TRAUMA_KEYWORDS
from utils.geo import haversine_distance, estimate_drive_time, build_maps_url
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TRAUMA_FILE = BASE_DIR / "data" / "trauma_centres.json"

async def fetch_services(
    category: str,
    lat: float,
    lng: float,
    radius: int,
    limit: int,
    db: Session,
    state_code: str
) -> Tuple[List[Dict[str, Any]], str]:
    """Returns (raw_results, data_source_label)"""
    
    # STEP 0 — Check cache first (fast path)
    cache_key = cache_service.get_cache_key(category, lat, lng, radius)
    cached = cache_service.get_cached_results(db, cache_key)
    if cached:
        return (cached[:limit], "cache")
        
    # STEP 1 — Try Google Places
    try:
        results = await google_places.search_nearby(category, lat, lng, radius, limit)
        if results:
            cache_service.save_to_cache(db, cache_key, category, results, "google_places", state_code)
            return (results, "google_places")
    except Exception as e:
        logger.warning(f"Google Places failed for {category}: {e}")
        
    # STEP 2 — Try Overpass API
    try:
        results = await overpass.search_nearby(category, lat, lng, radius, limit)
        if results:
            cache_service.save_to_cache(db, cache_key, category, results, "overpass", state_code)
            return (results, "overpass")
    except Exception as e:
        logger.warning(f"Overpass API failed for {category}: {e}")
        
    # STEP 3 — SQLite state-wide cache (last resort)
    results = cache_service.get_cached_by_state(db, category, state_code)
    if results:
        logger.info(f"Serving stale cache for {category} in {state_code}")
        return (results[:limit], "cache")
        
    # STEP 4 — Total failure
    logger.error(f"All data sources failed for {category}")
    return ([], "unavailable")

def build_service_result(
    raw: Dict[str, Any],
    user_lat: float,
    user_lng: float,
    source: str,
    state_code: str
) -> ServiceResult:
    distance_m = haversine_distance(user_lat, user_lng, raw["lat"], raw["lng"])
    drive_time_min = estimate_drive_time(distance_m)
    maps_url = build_maps_url(raw["lat"], raw["lng"], raw.get("id") if source == "google_places" else None)
    
    return ServiceResult(
        id=raw["id"],
        name=raw["name"],
        phone=raw.get("phone"),
        address=raw["address"],
        lat=raw["lat"],
        lng=raw["lng"],
        distance_m=distance_m,
        drive_time_min=drive_time_min,
        open_now=raw.get("open_now"),
        rating=raw.get("rating"),
        maps_url=maps_url,
        source=source,
        state=state_code
    )

def build_hospital_result(
    raw: Dict[str, Any],
    user_lat: float,
    user_lng: float,
    source: str,
    state_code: str
) -> HospitalResult:
    base = build_service_result(raw, user_lat, user_lng, source, state_code)
    
    name_lower = raw["name"].lower()
    is_trauma = any(kw in name_lower for kw in TRAUMA_KEYWORDS)
    
    return HospitalResult(
        **base.dict(),
        has_emergency=True,
        verified_trauma_centre=False,
        trauma_verification_method="keyword_match" if is_trauma else None,
        bed_type=None
    )

def load_trauma_centres(user_lat: float, user_lng: float) -> List[HospitalResult]:
    try:
        with open(TRAUMA_FILE, "r") as f:
            data = json.load(f)
            
        results = []
        for raw in data.get("verified_trauma_centres", []):
            distance_m = haversine_distance(user_lat, user_lng, raw["lat"], raw["lng"])
            drive_time_min = estimate_drive_time(distance_m)
            maps_url = build_maps_url(raw["lat"], raw["lng"], None)
            
            h = HospitalResult(
                id=raw["id"],
                name=raw["name"],
                phone=raw.get("phone"),
                address=raw["address"],
                lat=raw["lat"],
                lng=raw["lng"],
                distance_m=distance_m,
                drive_time_min=drive_time_min,
                open_now=None,
                rating=None,
                maps_url=maps_url,
                source="cache",
                state=raw["state"],
                has_emergency=True,
                verified_trauma_centre=True,
                trauma_verification_method="curated_list",
                bed_type=raw.get("bed_type")
            )
            results.append(h)
            
        results.sort(key=lambda x: x.distance_m)
        return results
    except Exception as e:
        logger.error(f"Failed to load trauma centres: {e}")
        return []
