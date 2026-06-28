import asyncio
import uuid
from datetime import datetime
from typing import Union, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from middleware.rate_limiter import limiter, LIMIT_TRIAGE
from database import get_db
from models.triage import TriageSession
from schemas.triage import (
    TriageStartRequest, TriageAnswerRequest,
    TriageInProgressResponse, TriageCompletedResponse,
    NearestTraumaCentre,
    CRITICAL_AUTO_STOP_THRESHOLD,
    get_severity_level, get_recommendation
)
from services.triage_service import get_triage_service
from services.fallback_orchestrator import (
    fetch_services, build_service_result, load_trauma_centres
)
from schemas.location import get_state_code
from utils.logger import get_logger

router = APIRouter(tags=["Medical Triage"])
logger = get_logger(__name__)


# ── Helper: build emergency services for completed triage ────

async def build_triage_emergency_services(
    lat: float,
    lng: float,
    db,
    state_code: str,
    severity: str
) -> tuple[dict, Optional[dict]]:
    """
    Build emergency_services dict and nearest_trauma_centre for
    completed triage response.

    For high/critical: return ambulance + trauma centres
    For medium: return hospital only
    For low: return empty dict (no emergency services needed)

    Returns: (emergency_services_dict, nearest_trauma_centre_dict)
    """
    emergency_services = {}
    nearest_trauma = None

    if severity == "low":
        return {}, None

    try:
        if severity in ["high", "critical"]:
            # Fetch ambulances (top 2)
            raw_amb, src_amb = await fetch_services(
                "ambulance", lat, lng,
                radius=5000, limit=2,
                db=db, state_code=state_code
            )
            emergency_services["ambulance"] = [
                build_service_result(r, lat, lng, src_amb, state_code).model_dump()
                for r in raw_amb
            ]

            # Add 108 helpline as first ambulance if list is short
            if len(emergency_services["ambulance"]) < 2:
                emergency_services["ambulance"].insert(0, {
                    "id": "helpline_108",
                    "name": "National Ambulance (108)",
                    "phone": "108",
                    "address": "Dial 108 for immediate ambulance",
                    "distance_m": 0,
                    "drive_time_min": None,
                    "maps_url": f"https://maps.google.com/?q={lat},{lng}",
                    "source": "cache",
                    "state": state_code
                })

        # Always include hospital for medium+ severity
        trauma_centres = load_trauma_centres(lat, lng)
        trauma_centres = sorted(
            trauma_centres, key=lambda x: x.distance_m
        )[:2]
        emergency_services["hospital"] = [
            t.model_dump() for t in trauma_centres
        ]

        # Nearest trauma centre (for prominent display)
        if trauma_centres:
            tc = trauma_centres[0]
            nearest_trauma = NearestTraumaCentre(
                id=tc.id,
                name=tc.name,
                phone=tc.phone,
                address=tc.address,
                distance_m=tc.distance_m,
                drive_time_min=tc.drive_time_min,
                verified_trauma_centre=True,
                maps_url=tc.maps_url
            ).model_dump()

    except Exception as e:
        logger.warning(f"Failed to fetch triage emergency services: {e}")
        # Return safe fallback
        emergency_services = {
            "ambulance": [{"name": "Dial 108", "phone": "108"}]
        }

    return emergency_services, nearest_trauma


# ── Helper: build suggested actions for completed triage ─────

def build_triage_actions(severity: str, nearest_trauma: dict) -> list[dict]:
    """Build suggested actions based on severity level."""
    actions = []

    if severity in ["high", "critical"]:
        actions.append({
            "label": "Call 108 (Ambulance)",
            "action": "call",
            "value": "108"
        })
        actions.append({
            "label": "Call 100 (Police)",
            "action": "call",
            "value": "100"
        })

    if nearest_trauma:
        actions.append({
            "label": f"Navigate to {nearest_trauma.get('name', 'Trauma Centre')}",
            "action": "navigate",
            "value": nearest_trauma.get("maps_url")
        })

    actions.append({
        "label": "Share my location",
        "action": "sos_share",
        "value": None
    })

    return actions


# ── Endpoint 1: POST /triage/start ───────────────────────────

@router.post(
    "/triage/start",
    response_model=TriageInProgressResponse
)
@limiter.limit(LIMIT_TRIAGE)
async def triage_start(
    request: Request,
    body: TriageStartRequest,
    db=Depends(get_db)
):
    """
    Begin a triage assessment. Flow:
    1. Validate location (warn if outside HR/DL, don't reject)
    2. Create TriageSession in DB
    3. Call Gemini to generate 5 contextual questions
    4. Store questions in DB
    5. Return first question
    """
    # Get state code (warn but don't reject — triage works anywhere)
    state_code = get_state_code(
        body.location.lat, body.location.lng
    ) or "HR"  # default to HR if outside bounds

    # Generate questions via Gemini (sync, run in thread)
    triage_svc = get_triage_service()

    try:
        questions = await asyncio.to_thread(
            triage_svc.generate_questions,
            body.initial_description,
            body.lang
        )
    except Exception as e:
        logger.error(f"Question generation failed: {e}")
        questions = triage_svc._get_fallback_questions(body.lang)

    # Create triage session in DB
    triage_id = str(uuid.uuid4())
    triage_session = TriageSession(
        id=triage_id,
        session_id=body.session_id,
        lat=body.location.lat,
        lng=body.location.lng,
        state_code=state_code,
        lang=body.lang,
        initial_description=body.initial_description,
        status="in_progress",
        questions=questions,
        answers=[],
        current_question_index=0,
        severity_score=0.0
    )
    db.add(triage_session)
    db.commit()
    db.refresh(triage_session)

    first_question = questions[0]["question"]

    logger.info(
        f"Triage started: {triage_id} "
        f"for session {body.session_id} "
        f"({len(questions)} questions)"
    )

    return TriageInProgressResponse(
        triage_id=triage_id,
        session_id=body.session_id,
        status="in_progress",
        current_question=first_question,
        question_index=1,        # 1-based for display
        total_questions=len(questions),
        severity_score_so_far=0.0
    )


# ── Endpoint 2: POST /triage/answer ──────────────────────────

@router.post(
    "/triage/answer",
    response_model=Union[TriageInProgressResponse, TriageCompletedResponse]
)
@limiter.limit(LIMIT_TRIAGE)
async def triage_answer(
    request: Request,
    body: TriageAnswerRequest,
    db=Depends(get_db)
):
    """
    Submit an answer to the current triage question. Flow:
    1. Load triage session from DB
    2. Validate session is in_progress and session_id matches
    3. Score the answer via Gemini
    4. Update running severity score
    5. Check auto-stop condition (score >= 8.0)
    6. If more questions AND not auto-stopped: return next question
    7. If all questions answered OR auto-stopped: finalize + return results
    """
    # Step 1: Load triage session
    triage = db.query(TriageSession).filter(
        TriageSession.id == body.triage_id
    ).first()

    if not triage:
        raise HTTPException(
            status_code=404,
            detail="Triage session not found",
            headers={"X-Error-Code": "SESSION_NOT_FOUND"}
        )

    # Step 2: Validate state
    if triage.status != "in_progress":
        raise HTTPException(
            status_code=400,
            detail=f"Triage is already '{triage.status}'. "
                   f"Start a new triage assessment.",
            headers={"X-Error-Code": "MISSING_PARAMS"}
        )

    if triage.session_id != body.session_id:
        raise HTTPException(
            status_code=403,
            detail="Session ID does not match this triage",
            headers={"X-Error-Code": "MISSING_PARAMS"}
        )

    current_idx = triage.current_question_index
    questions = triage.questions or []

    if current_idx >= len(questions):
        raise HTTPException(
            status_code=400,
            detail="All questions already answered",
            headers={"X-Error-Code": "MISSING_PARAMS"}
        )

    # Step 3: Score the answer via Gemini
    current_question = questions[current_idx]
    triage_svc = get_triage_service()

    try:
        score_contribution = await asyncio.to_thread(
            triage_svc.score_answer,
            current_question["question"],
            body.answer,
            current_question["weight"]
        )
    except Exception as e:
        logger.warning(f"Answer scoring failed: {e}")
        score_contribution = current_question["weight"] * 0.5

    # Step 4: Store answer (CRITICAL: copy list to trigger SQLAlchemy update)
    new_answer = {
        "answer": body.answer,
        "question": current_question["question"],
        "score_contribution": score_contribution
    }
    triage.answers = list(triage.answers or []) + [new_answer]

    # Step 5: Compute running severity score
    triage.current_question_index = current_idx + 1
    triage.severity_score = triage_svc.compute_severity_score(
        questions, triage.answers
    )
    triage.updated_at = datetime.utcnow()

    logger.debug(
        f"Triage {body.triage_id}: Q{current_idx + 1} answered. "
        f"Score: {triage.severity_score}"
    )

    # Step 6: Check auto-stop OR all questions done
    all_answered = triage.current_question_index >= len(questions)
    auto_stop = triage.severity_score >= CRITICAL_AUTO_STOP_THRESHOLD

    if auto_stop:
        logger.warning(
            f"Triage AUTO-STOPPED: score={triage.severity_score} "
            f"(>= {CRITICAL_AUTO_STOP_THRESHOLD})"
        )

    if all_answered or auto_stop:
        # ── FINALIZE TRIAGE ──────────────────────────────────
        severity = get_severity_level(triage.severity_score)
        recommendation = get_recommendation(severity, triage.lang)

        # Fetch emergency services
        emergency_services, nearest_trauma = \
            await build_triage_emergency_services(
                triage.lat, triage.lng, db,
                triage.state_code or "HR",
                severity
            )

        # Persist final state
        triage.status = "completed"
        triage.severity_level = severity
        triage.recommendation = recommendation
        triage.emergency_services = emergency_services
        triage.nearest_trauma_centre = nearest_trauma
        triage.auto_stopped = auto_stop
        db.commit()

        logger.info(
            f"Triage {body.triage_id} COMPLETED: "
            f"severity={severity} score={triage.severity_score}"
        )

        # Build suggested actions
        suggested = build_triage_actions(severity, nearest_trauma)

        return TriageCompletedResponse(
            triage_id=body.triage_id,
            session_id=body.session_id,
            status="completed",
            severity=severity,
            severity_score=triage.severity_score,
            recommendation=recommendation,
            auto_stopped=auto_stop,
            nearest_trauma_centre=nearest_trauma,
            emergency_services=emergency_services,
            suggested_actions=suggested
        )

    else:
        # ── RETURN NEXT QUESTION ─────────────────────────────
        db.commit()
        next_question = questions[triage.current_question_index]

        return TriageInProgressResponse(
            triage_id=body.triage_id,
            session_id=body.session_id,
            status="in_progress",
            current_question=next_question["question"],
            question_index=triage.current_question_index + 1,  # 1-based
            total_questions=len(questions),
            severity_score_so_far=triage.severity_score
        )
