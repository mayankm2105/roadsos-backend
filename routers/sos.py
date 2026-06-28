import asyncio
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from middleware.rate_limiter import limiter, LIMIT_SOS
from fastapi.responses import JSONResponse
from database import get_db
from models.sos import SOSLink
from schemas.sos import (
    SOSCreateRequest, SOSCreateResponse,
    SOSViewResponse, AccidentLocation,
    SOSResolveRequest, SOSResolveResponse
)
from utils.sos_helpers import (
    generate_sos_id, build_shareable_link,
    build_whatsapp_link, build_whatsapp_link_for_contact
)
from services.fallback_orchestrator import (
    fetch_services, build_service_result, build_hospital_result,
    load_trauma_centres
)
from schemas.location import get_state_code, is_within_coverage
from config import settings
from utils.logger import get_logger

router = APIRouter(tags=["SOS Emergency Share"])
logger = get_logger(__name__)


# ── Helper: fetch and snapshot nearby services ───────────────

async def snapshot_nearby_services(
    lat: float,
    lng: float,
    db,
    state_code: str
) -> dict:
    """
    Fetch top 2 results for ambulance, hospital, police concurrently.
    This snapshot is stored in the SOS record AND returned in GET /sos/{id}.

    Uses asyncio.gather with return_exceptions=True so one failing
    category doesn't break the whole SOS creation.
    """
    CATEGORIES = ["ambulance", "police"]
    results = {}

    # Fetch ambulance + police concurrently
    tasks = [
        fetch_services(cat, lat, lng, radius=5000,
                       limit=2, db=db, state_code=state_code)
        for cat in CATEGORIES
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, cat in enumerate(CATEGORIES):
        raw = raw_results[i]
        if isinstance(raw, Exception):
            logger.warning(f"SOS service fetch failed for {cat}: {raw}")
            results[cat] = []
        else:
            raw_list, source = raw
            results[cat] = [
                build_service_result(r, lat, lng, source, state_code).dict()
                for r in raw_list
            ]

    # Always include hardcoded 108 as first ambulance
    ambulance_108 = {
        "id": "helpline_108",
        "name": "National Ambulance Service (108)",
        "phone": "108",
        "address": "National Emergency — Dial 108 immediately",
        "lat": lat,
        "lng": lng,
        "distance_m": 0,
        "drive_time_min": None,
        "open_now": True,
        "rating": None,
        "maps_url": f"https://maps.google.com/?q={lat},{lng}",
        "source": "cache",
        "state": state_code
    }
    results["ambulance"] = [ambulance_108] + results.get("ambulance", [])

    # Hospital: use curated trauma centres
    try:
        trauma = load_trauma_centres(lat, lng)
        trauma_sorted = sorted(trauma, key=lambda x: x.distance_m)[:2]
        results["hospital"] = [t.dict() for t in trauma_sorted]
    except Exception as e:
        logger.warning(f"Trauma centre load failed for SOS: {e}")
        results["hospital"] = []

    return results


# ── Endpoint 1: POST /sos/create ─────────────────────────────

@router.post(
    "/sos/create",
    response_model=SOSCreateResponse,
    status_code=201
)
@limiter.limit(LIMIT_SOS)
async def create_sos(
    request: Request,
    body: SOSCreateRequest,
    db=Depends(get_db)
):
    """
    Create an SOS emergency share link.
    """
    state_code = get_state_code(
        body.location.lat, body.location.lng
    ) or "HR"

    sos_id = None
    for attempt in range(3):
        candidate = generate_sos_id()
        existing = db.query(SOSLink).filter(
            SOSLink.id == candidate
        ).first()
        if not existing:
            sos_id = candidate
            break

    if not sos_id:
        import uuid
        sos_id = str(uuid.uuid4())[:8].upper()

    nearby_services = await snapshot_nearby_services(
        body.location.lat,
        body.location.lng,
        db,
        state_code
    )
    
    nearby_services["_severity"] = body.severity
    nearby_services["_additional_info"] = body.additional_info or ""

    shareable_link = build_shareable_link(sos_id)
    whatsapp_link = build_whatsapp_link(
        sos_id,
        body.severity,
        body.additional_info or ""
    )

    contact_links = []
    for contact in (body.emergency_contacts or []):
        wa_url = build_whatsapp_link_for_contact(
            sos_id,
            contact.phone,
            body.severity,
            body.additional_info or ""
        )
        contact_links.append({
            "name": contact.name,
            "phone": contact.phone,
            "whatsapp_url": wa_url
        })

    now = datetime.utcnow()
    expires_at = now + timedelta(hours=settings.SOS_LINK_TTL_HOURS)

    sos_record = SOSLink(
        id=sos_id,
        created_at=now,
        expires_at=expires_at,
        lat=body.location.lat,
        lng=body.location.lng,
        description=body.additional_info,
        state_code=state_code,
        status="active",
        nearby_services=nearby_services,
        whatsapp_url=whatsapp_link
    )
    db.add(sos_record)
    db.commit()

    logger.info(
        f"SOS created: {sos_id} at ({body.location.lat},"
        f"{body.location.lng}) severity={body.severity}"
    )

    return SOSCreateResponse(
        sos_id=sos_id,
        shareable_link=shareable_link,
        whatsapp_link=whatsapp_link,
        contact_whatsapp_links=contact_links,
        expires_at=expires_at.isoformat() + "Z",
        ttl_hours=settings.SOS_LINK_TTL_HOURS
    )


# ── Endpoint 2: GET /sos/{sos_id} ───────────────────────────

@router.get(
    "/sos/{sos_id}",
    response_model=SOSViewResponse
)
async def get_sos(
    sos_id: str,
    db=Depends(get_db)
):
    """
    Public SOS view endpoint — no auth required.
    """
    sos = db.query(SOSLink).filter(SOSLink.id == sos_id).first()

    if not sos:
        raise HTTPException(
            status_code=404,
            detail="SOS link not found",
            headers={"X-Error-Code": "SOS_NOT_FOUND"}
        )

    now = datetime.utcnow()
    if sos.expires_at and now > sos.expires_at:
        if sos.status == "active":
            sos.status = "expired"
            db.commit()

        return JSONResponse(
            status_code=410,
            content={
                "error": {
                    "code": "SOS_EXPIRED",
                    "message": "This SOS link has expired (24-hour TTL).",
                    "expired_at": sos.expires_at.isoformat() + "Z"
                }
            }
        )

    nearby = sos.nearby_services or {
        "ambulance": [], "hospital": [], "police": []
    }
    
    severity = nearby.get("_severity", "high") if isinstance(nearby, dict) else "high"
    additional_info = nearby.get("_additional_info", "") if isinstance(nearby, dict) else ""

    accident_location = AccidentLocation(
        lat=sos.lat,
        lng=sos.lng,
        address=sos.address,
        state=sos.state_code
    )

    logger.info(f"SOS viewed: {sos_id} (status: {sos.status})")

    return SOSViewResponse(
        sos_id=sos_id,
        status=sos.status,
        accident_location=accident_location,
        created_at=sos.created_at.isoformat() + "Z",
        severity=severity,
        additional_info=additional_info if additional_info else None,
        nearest_services={
            k: v for k, v in nearby.items()
            if not k.startswith("_")
        } if isinstance(nearby, dict) else nearby
    )


# ── Endpoint 3: PATCH /sos/{sos_id}/resolve ─────────────────

@router.patch(
    "/sos/{sos_id}/resolve",
    response_model=SOSResolveResponse
)
def resolve_sos(
    sos_id: str,
    request: SOSResolveRequest,
    db=Depends(get_db)
):
    """
    Mark an SOS as resolved. Sync endpoint (no async needed here).
    """
    sos = db.query(SOSLink).filter(SOSLink.id == sos_id).first()

    if not sos:
        raise HTTPException(
            status_code=404,
            detail="SOS link not found",
            headers={"X-Error-Code": "SOS_NOT_FOUND"}
        )

    if sos.status == "resolved":
        raise HTTPException(
            status_code=400,
            detail="SOS is already resolved",
            headers={"X-Error-Code": "MISSING_PARAMS"}
        )

    now = datetime.utcnow()
    sos.status = "resolved"
    db.commit()

    logger.info(
        f"SOS resolved: {sos_id} "
        f"by {request.resolved_by}"
    )

    return SOSResolveResponse(
        sos_id=sos_id,
        status="resolved",
        resolved_at=now.isoformat() + "Z"
    )
