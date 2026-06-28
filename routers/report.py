import asyncio
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from models.report import Report
from models.session import ChatSession
from schemas.report import (
    ReportGenerateRequest, ReportGenerateResponse, FIRDraft
)
from services.report_service import (
    get_report_service,
    format_fir_as_plain_text,
    build_fir_whatsapp_url
)
from services.fallback_orchestrator import fetch_services, build_service_result
from schemas.location import get_state_code
from utils.logger import get_logger
from typing import Optional, List, Generator

router = APIRouter(tags=["FIR Report Generator"])
logger = get_logger(__name__)


# ── Helper: fetch nearest police station name + phone ────────

async def get_nearest_police_info(
    lat: Optional[float],
    lng: Optional[float],
    db,
    state_code: str
) -> Optional[str]:
    """
    Fetch the nearest police station name and phone for inclusion
    in the FIR. Returns formatted string: "Name, Phone" or None.

    Uses Phase 2 fetch_services with limit=1 (just need the nearest).
    Gracefully returns None if fetch fails — FIR generation continues.
    """
    if not lat or not lng:
        return None

    try:
        raw, source = await fetch_services(
            "police", lat, lng,
            radius=10000,  # wider radius for police
            limit=1,
            db=db,
            state_code=state_code
        )
        if raw:
            police = build_service_result(
                raw[0], lat, lng, source, state_code
            )
            phone_part = f", {police.phone}" if police.phone else ""
            return f"{police.name}{phone_part}"
    except Exception as e:
        logger.warning(f"Could not fetch nearest police for FIR: {e}")

    return None


# ── Endpoint 1: POST /report/generate ────────────────────────

@router.post(
    "/report/generate",
    response_model=ReportGenerateResponse,
    status_code=200
)
async def generate_report(
    request: ReportGenerateRequest,
    db=Depends(get_db)
):
    """
    Generate FIR draft from chat history + additional info. Flow:

    1. Load chat session → extract user messages as context
    2. Get last known location from session
    3. Fetch nearest police station (for FIR inclusion)
    4. Call Gemini to generate structured FIR (in thread pool)
    5. Format as plain text
    6. Build WhatsApp share URL
    7. Persist Report to DB
    8. Return full report response

    The session does NOT need to be cleared or modified.
    This endpoint is read-only on the chat session.
    """

    # Step 1: Load chat session
    session = db.query(ChatSession).filter(
        ChatSession.id == request.session_id,
        ChatSession.is_cleared == False
    ).first()

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Chat session not found. Start a chat first "
                   "to provide accident context for the FIR.",
            headers={"X-Error-Code": "SESSION_NOT_FOUND"}
        )

    # Step 2: Extract location from session
    lat = session.last_location_lat
    lng = session.last_location_lng
    state_code = get_state_code(lat, lng) if lat and lng else "HR"

    # Step 3: Get nearest police station
    nearest_police = await get_nearest_police_info(
        lat, lng, db, state_code or "HR"
    )

    # Step 4: Extract chat context
    report_svc = get_report_service()
    chat_context = report_svc._extract_chat_context(
        session.messages or []
    )

    logger.info(
        f"Generating FIR for session {request.session_id} "
        f"({len(session.messages or [])} messages, "
        f"lang={request.lang})"
    )

    # Step 5: Generate FIR via Gemini (sync → run in thread)
    fir_draft = await asyncio.to_thread(
        report_svc.generate_fir,
        chat_context,
        request.additional_info,
        lat,
        lng,
        nearest_police,
        request.lang
    )

    # Step 6: Format as plain text
    download_text = format_fir_as_plain_text(fir_draft, request.lang)

    # Step 7: Generate report ID + WhatsApp URL
    report_id = str(uuid.uuid4())
    whatsapp_url = build_fir_whatsapp_url(download_text, report_id)

    # Step 8: Persist to DB
    # Map FIRDraft fields to Report model columns
    # Check models/report.py for exact column names
    report_record = Report(
        id=report_id,
        session_id=request.session_id,
        created_at=datetime.utcnow(),
        incident_date=fir_draft.incident_date,
        incident_location=fir_draft.location,
        lat=lat,
        lng=lng,
        description=fir_draft.description,
        vehicles_involved=fir_draft.vehicles_involved,
        injuries_count=fir_draft.injuries_count,
        witness_details=fir_draft.witnesses,
        nearest_police_station=fir_draft.nearest_police_station,
        reporting_person_name=fir_draft.reporting_person,
        reporting_person_phone=fir_draft.contact,
        fir_json=fir_draft.model_dump(),
        download_text=download_text,
        whatsapp_url=whatsapp_url,
        lang=request.lang
    )
    db.add(report_record)
    db.commit()

    logger.info(f"FIR report saved: {report_id}")

    generated_at = datetime.utcnow().isoformat() + "Z"

    return ReportGenerateResponse(
        report_id=report_id,
        session_id=request.session_id,
        generated_at=generated_at,
        lang=request.lang,
        fir_draft=fir_draft,
        download_text=download_text,
        share_whatsapp_url=whatsapp_url
    )


# ── Endpoint 2: GET /report/{report_id} ──────────────────────

@router.get(
    "/report/{report_id}",
    response_model=ReportGenerateResponse
)
def get_report(
    report_id: str,
    db=Depends(get_db)
):
    """
    Retrieve a previously generated FIR report by ID.
    Sync endpoint — just a DB lookup, no external calls.

    Returns 404 if report_id not found.
    """
    report = db.query(Report).filter(
        Report.id == report_id
    ).first()

    if not report:
        raise HTTPException(
            status_code=404,
            detail="Report not found",
            headers={"X-Error-Code": "SESSION_NOT_FOUND"}
        )

    # Reconstruct FIRDraft from stored JSON
    fir_draft = FIRDraft(**(report.fir_json or {}))

    return ReportGenerateResponse(
        report_id=report.id,
        session_id=report.session_id or "",
        generated_at=report.created_at.isoformat() + "Z",
        lang=report.lang or "en",
        fir_draft=fir_draft,
        download_text=report.download_text or "",
        share_whatsapp_url=report.whatsapp_url or ""
    )
