import asyncio
from datetime import datetime
from typing import Annotated, List, Optional
from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from schemas.services import (
    ServiceListResponse, HospitalListResponse, AmbulanceListResponse,
    TowingListResponse, MechanicListResponse, NearbyResponse,
    NearbyLocationInfo, NearbyResults, TowingResult, MechanicResult,
    AmbulanceResult, NATIONAL_HELPLINES
)
from schemas.location import get_state_code
from services.fallback_orchestrator import (
    fetch_services, build_service_result, build_hospital_result,
    load_trauma_centres
)
from services import google_places
from utils.geo import haversine_distance, estimate_drive_time

router = APIRouter(tags=["Emergency Services"])

def validate_region(lat: float, lng: float) -> str:
    """Returns state_code or raises 400."""
    state_code = get_state_code(lat, lng)
    if not state_code:
        raise HTTPException(
            status_code=400,
            detail="Location outside Haryana/Delhi coverage area",
            headers={"X-Error-Code": "REGION_OUT_OF_SCOPE"}
        )
    return state_code

@router.get("/services/police", response_model=ServiceListResponse)
async def get_police(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(default=5000, ge=100, le=50000),
    limit: int = Query(default=10, ge=1, le=20),
    lang: str = Query(default="en"),
    db: Session = Depends(get_db)
):
    state_code = validate_region(lat, lng)
    raw_results, data_source = await fetch_services(
        "police", lat, lng, radius, limit, db, state_code)
        
    results = [build_service_result(r, lat, lng, data_source, state_code)
               for r in raw_results]
               
    # Fetch phone for top 3 results if missing and source is google_places
    if data_source == "google_places":
        for i, res in enumerate(results[:3]):
            if not res.phone and res.id:
                phone = await google_places.get_place_phone(res.id)
                if phone:
                    res.phone = phone
                    
    results.sort(key=lambda x: x.distance_m)
    
    return ServiceListResponse(
        category="police",
        data_source=data_source,
        count=len(results),
        results=results,
        fetched_at=datetime.utcnow().isoformat() + "Z"
    )

@router.get("/services/hospitals", response_model=HospitalListResponse)
async def get_hospitals(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(default=5000, ge=100, le=50000),
    limit: int = Query(default=10, ge=1, le=20),
    lang: str = Query(default="en"),
    trauma_only: bool = Query(default=False),
    db: Session = Depends(get_db)
):
    state_code = validate_region(lat, lng)
    
    trauma_centres = load_trauma_centres(lat, lng)
    trauma_centres = [t for t in trauma_centres if t.distance_m <= radius]
    
    if trauma_only:
        return HospitalListResponse(
            category="hospital",
            data_source="cache",
            count=len(trauma_centres),
            results=trauma_centres,
            fetched_at=datetime.utcnow().isoformat() + "Z"
        )
        
    raw_results, data_source = await fetch_services(
        "hospital", lat, lng, radius, limit, db, state_code)
        
    live_results = [build_hospital_result(r, lat, lng, data_source, state_code)
                    for r in raw_results]
                    
    if data_source == "google_places":
        for i, res in enumerate(live_results[:3]):
            if not res.phone and res.id:
                phone = await google_places.get_place_phone(res.id)
                if phone:
                    res.phone = phone
                    
    curated_ids = {t.id for t in trauma_centres}
    live_results = [r for r in live_results if r.id not in curated_ids]
    
    combined = trauma_centres + live_results
    combined.sort(key=lambda x: (not x.verified_trauma_centre, x.distance_m))
    combined = combined[:limit]
    
    return HospitalListResponse(
        category="hospital",
        data_source=data_source,
        count=len(combined),
        results=combined,
        fetched_at=datetime.utcnow().isoformat() + "Z"
    )

@router.get("/services/ambulances", response_model=AmbulanceListResponse)
async def get_ambulances(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(default=5000, ge=100, le=50000),
    limit: int = Query(default=10, ge=1, le=20),
    lang: str = Query(default="en"),
    type: str = Query(default="all"),
    db: Session = Depends(get_db)
):
    state_code = validate_region(lat, lng)
    
    hardcoded_ambulance = AmbulanceResult(
        id="helpline_108",
        name="National Ambulance Service (108)",
        phone="108",
        address="National Emergency Service — dial 108",
        lat=lat,
        lng=lng,
        distance_m=0,
        drive_time_min=None,
        open_now=True,
        rating=None,
        maps_url=f"https://maps.google.com/?q={lat},{lng}",
        source="cache",
        state=state_code,
        ambulance_type="government",
        national_helpline="108",
        response_time_est_min=8
    )
    
    raw_results, data_source = await fetch_services(
        "ambulance", lat, lng, radius, limit - 1, db, state_code)
        
    live_results = []
    for r in raw_results:
        base_res = build_service_result(r, lat, lng, data_source, state_code).dict()
        live_results.append(AmbulanceResult(
            **base_res,
            ambulance_type="private",  # default to private for live search
            national_helpline="108",
            response_time_est_min=estimate_drive_time(
                haversine_distance(lat, lng, r["lat"], r["lng"])
            )
        ))
        
    all_results = [hardcoded_ambulance] + live_results
    
    if type == "government":
        all_results = [r for r in all_results if r.ambulance_type == "government"]
    elif type == "private":
        all_results = [r for r in all_results if r.ambulance_type == "private"]
        
    return AmbulanceListResponse(
        category="ambulance",
        data_source=data_source,
        count=len(all_results),
        results=all_results,
        national_helplines=NATIONAL_HELPLINES,
        fetched_at=datetime.utcnow().isoformat() + "Z"
    )

@router.get("/services/towing", response_model=TowingListResponse)
async def get_towing(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(default=5000, ge=100, le=50000),
    limit: int = Query(default=10, ge=1, le=20),
    lang: str = Query(default="en"),
    db: Session = Depends(get_db)
):
    state_code = validate_region(lat, lng)
    raw_results, data_source = await fetch_services(
        "towing", lat, lng, radius, limit, db, state_code)
        
    results = []
    for r in raw_results:
        base_res = build_service_result(r, lat, lng, data_source, state_code).dict()
        results.append(TowingResult(
            **base_res,
            is_24x7=False,
            vehicle_types=["car", "bike", "truck"]
        ))
        
    results.sort(key=lambda x: x.distance_m)
    
    return TowingListResponse(
        category="towing",
        data_source=data_source,
        count=len(results),
        results=results,
        fetched_at=datetime.utcnow().isoformat() + "Z"
    )

@router.get("/services/mechanics", response_model=MechanicListResponse)
async def get_mechanics(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(default=5000, ge=100, le=50000),
    limit: int = Query(default=10, ge=1, le=20),
    lang: str = Query(default="en"),
    service: str = Query(default="all"),
    db: Session = Depends(get_db)
):
    state_code = validate_region(lat, lng)
    raw_results, data_source = await fetch_services(
        "mechanic", lat, lng, radius, limit, db, state_code)
        
    filtered_results = raw_results
    if service != "all":
        keywords = {
            "puncture": ["puncture", "tyre", "tire"],
            "breakdown": ["breakdown", "repair", "workshop"],
            "fuel": ["petrol", "fuel", "diesel", "gas"]
        }.get(service, [])
        
        filtered_try = [
            r for r in raw_results 
            if any(kw in str(r.get("name", "")).lower() for kw in keywords)
        ]
        if filtered_try:
            filtered_results = filtered_try
            
    results = []
    for r in filtered_results:
        base_res = build_service_result(r, lat, lng, data_source, state_code).dict()
        
        # detect subtype based on keywords
        name_lower = str(r.get("name", "")).lower()
        subtype = None
        if any(kw in name_lower for kw in ["puncture", "tyre", "tire"]):
            subtype = "puncture"
        elif any(kw in name_lower for kw in ["petrol", "fuel", "diesel", "gas"]):
            subtype = "fuel"
        elif any(kw in name_lower for kw in ["breakdown", "repair", "workshop"]):
            subtype = "breakdown"
            
        results.append(MechanicResult(
            **base_res,
            service_subtype=subtype
        ))
        
    results.sort(key=lambda x: x.distance_m)
    
    return MechanicListResponse(
        category="mechanic",
        data_source=data_source,
        count=len(results),
        results=results[:limit],
        fetched_at=datetime.utcnow().isoformat() + "Z"
    )

@router.get("/services/nearby", response_model=NearbyResponse)
async def get_nearby(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(default=5000, ge=100, le=50000),
    limit: int = Query(default=10, ge=1, le=20),
    lang: str = Query(default="en"),
    categories: str = Query(default="all"),
    db: Session = Depends(get_db)
):
    state_code = validate_region(lat, lng)
    
    valid_categories = ["police", "hospital", "ambulance", "towing", "mechanic"]
    if categories == "all":
        cats = valid_categories
    else:
        cats = [c.strip() for c in categories.split(",") if c.strip() in valid_categories]
        
    tasks = {
        cat: fetch_services(cat, lat, lng, radius, max(1, limit // 2), db, state_code)
        for cat in cats
    }
    
    raw_responses = await asyncio.gather(*tasks.values(), return_exceptions=True)
    
    results = NearbyResults()
    sources = []
    
    for i, cat in enumerate(cats):
        response = raw_responses[i]
        if isinstance(response, Exception):
            continue
            
        raw_res, source = response
        if source != "unavailable":
            sources.append(source)
            
        if cat == "police":
            results.police = [build_service_result(r, lat, lng, source, state_code) for r in raw_res]
        elif cat == "hospital":
            results.hospital = [build_hospital_result(r, lat, lng, source, state_code) for r in raw_res]
        elif cat == "ambulance":
            results.ambulance = [
                AmbulanceResult(
                    **build_service_result(r, lat, lng, source, state_code).dict(),
                    ambulance_type="private",
                    national_helpline="108",
                    response_time_est_min=estimate_drive_time(haversine_distance(lat, lng, r["lat"], r["lng"]))
                ) for r in raw_res
            ]
        elif cat == "towing":
            results.towing = [
                TowingResult(
                    **build_service_result(r, lat, lng, source, state_code).dict(),
                    is_24x7=False,
                    vehicle_types=["car", "bike", "truck"]
                ) for r in raw_res
            ]
        elif cat == "mechanic":
            results.mechanic = [
                MechanicResult(
                    **build_service_result(r, lat, lng, source, state_code).dict(),
                    service_subtype=None
                ) for r in raw_res
            ]

    # Calculate dominant data source
    dominant_source = "unavailable"
    if sources:
        dominant_source = max(set(sources), key=sources.count)
        
    return NearbyResponse(
        location=NearbyLocationInfo(lat=lat, lng=lng, state=state_code),
        data_source=dominant_source,
        results=results,
        fetched_at=datetime.utcnow().isoformat() + "Z"
    )
