import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from middleware.rate_limiter import limiter, LIMIT_CHAT, LIMIT_VOICE
from database import get_db
from models.session import ChatSession
from typing import Optional
from schemas.chat import (
    LocationInput, ChatMessageRequest, ReplyBlock, ChatMessageResponse, VoiceChatResponse,
    SuggestedAction, MessageRecord, SessionHistoryResponse, SessionClearResponse,
    INTENT_SERVICE_MAP, build_suggested_actions
)
from fastapi import File, Form, UploadFile
from utils.audio import validate_audio_file, save_temp_audio, cleanup_temp_file
from services.whisper_stt import transcribe_audio
from services.gemini_chat import get_gemini_service
from services.fallback_orchestrator import (
    fetch_services, build_service_result, build_hospital_result,
    load_trauma_centres
)
from schemas.location import get_state_code
from utils.logger import get_logger
from datetime import datetime
import json
import uuid

router = APIRouter(tags=["AI Chatbot"])
logger = get_logger(__name__)

def get_or_create_session(session_id: str, db) -> ChatSession:
    """
    Fetch existing session from DB or create a new one.
    If session is marked is_cleared=True, treat as new (reset messages).
    """
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id
    ).first()

    if not session:
        session = ChatSession(
            id=session_id,
            messages=[],
            lang="en"
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    elif session.is_cleared:
        session.messages = []
        session.is_cleared = False
        db.commit()

    return session


def append_message(
    session: ChatSession,
    role: str,
    content: str,
    msg_type: str = "text",
    intent: Optional[str] = None,
    db = None
) -> None:
    """
    Append a new message to session.messages JSON list and persist.
    NOTE: SQLAlchemy does not auto-detect mutations in JSON columns.
    Use the copy trick: session.messages = [*session.messages, new_msg]
    """
    new_msg = {
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "type": msg_type,
    }
    if intent:
        new_msg["intent"] = intent

    # CRITICAL: copy the list — SQLAlchemy won't detect in-place mutation
    session.messages = list(session.messages or []) + [new_msg]
    session.updated_at = datetime.utcnow()
    if db:
        db.commit()


async def fetch_services_for_intent(
    intent: str,
    lat: float,
    lng: float,
    db,
    state_code: str
) -> dict:
    """
    Given a detected intent, call Phase 2 fetch_services for the
    appropriate service categories. Returns dict of category → results.

    Uses INTENT_SERVICE_MAP to know which categories to fetch.
    Fetches with: radius=5000, limit=3 (top 3 is enough for chat context).
    Converts raw results to ServiceResult using build_service_result().
    Returns result as list of dicts (use .dict() on each ServiceResult).
    """
    categories = INTENT_SERVICE_MAP.get(intent, [])
    if not categories:
        return {}

    services_dict = {}

    for category in categories:
        try:
            if category == "hospital":
                # For hospitals in chat, use trauma centres first
                trauma = load_trauma_centres(lat, lng)
                trauma = sorted(trauma, key=lambda x: x.distance_m)[:3]
                services_dict["hospital"] = [t.dict() for t in trauma]
            else:
                raw, source = await fetch_services(
                    category, lat, lng,
                    radius=5000, limit=3,
                    db=db, state_code=state_code
                )
                results = [
                    build_service_result(r, lat, lng, source, state_code)
                    for r in raw
                ]
                services_dict[category] = [r.dict() for r in results]
        except Exception as e:
            logger.warning(f"Service fetch failed for {category}: {e}")
            services_dict[category] = []

    return services_dict


@router.post("/chat/message", response_model=ChatMessageResponse)
@limiter.limit(LIMIT_CHAT)
async def chat_message(
    request: Request,
    body: ChatMessageRequest,
    db = Depends(get_db)
):
    """
    Main chat endpoint. Flow:
    1. Get or create session
    2. Append user message to history
    3. Detect language from message
    4. Send to Gemini with full history
    5. Extract intent from Gemini response
    6. If intent maps to services → fetch them from Phase 2
    7. Append assistant reply to history
    8. Build suggested actions
    9. Update session location
    10. Return full ChatMessageResponse
    """

    # Step 1: Session management
    session = get_or_create_session(body.session_id, db)

    # Step 2: Append user message
    append_message(
        session, "user", body.message, "text", None, db
    )

    # Step 3: Detect language
    gemini_svc = get_gemini_service()
    detected_lang = gemini_svc.detect_language(body.message)
    effective_lang = body.lang if body.lang != "en" else detected_lang

    # Step 4: Get all current messages for history context
    history = list(session.messages or [])

    # Step 5: Call Gemini
    try:
        raw_response = await asyncio.to_thread(
            gemini_svc.send_message,
            body.message,
            history[:-1],  # history BEFORE the current message
            effective_lang
        )
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        raise HTTPException(
            status_code=502,
            detail="AI service is temporarily unavailable. Please try again.",
            headers={"X-Error-Code": "AI_ERROR"}
        )

    # Step 6: Extract intent and clean reply
    clean_reply, intent = gemini_svc.extract_intent(raw_response)

    # Step 7: Check if triage should be triggered
    triage_triggered = (intent == "start_triage")

    # Step 8: Validate region + fetch services if needed
    state_code = get_state_code(body.location.lat, body.location.lng)

    services_data = {}
    if state_code and intent in INTENT_SERVICE_MAP and \
       INTENT_SERVICE_MAP[intent]:
        services_data = await fetch_services_for_intent(
            intent,
            body.location.lat,
            body.location.lng,
            db,
            state_code
        )

    # Step 9: Append assistant reply to history (store raw with INTENT line)
    append_message(
        session, "assistant", raw_response, "text", intent, db
    )

    # Step 10: Update session location
    session.last_location_lat = body.location.lat
    session.last_location_lng = body.location.lng
    session.lang = effective_lang
    db.commit()

    # Step 11: Build suggested actions
    suggested = build_suggested_actions(intent, services_data)

    return ChatMessageResponse(
        session_id=body.session_id,
        reply=ReplyBlock(text=clean_reply, lang=effective_lang),
        intent=intent,
        triage_triggered=triage_triggered,
        services=services_data if services_data else None,
        suggested_actions=suggested
    )


@router.post("/chat/voice", response_model=VoiceChatResponse)
@limiter.limit(LIMIT_VOICE)
async def chat_voice(
    request: Request,
    audio: UploadFile = File(..., description="Audio file WAV/MP3/OGG/WebM"),
    session_id: str = Form(...),
    lat: float = Form(...),
    lng: float = Form(...),
    lang: str = Form(default="en"),
    db=Depends(get_db)
):
    """
    Voice input endpoint. Full flow:
    1. Validate audio file format
    2. Save to temp file
    3. Transcribe with Whisper (in thread pool)
    4. Pass transcription through existing Gemini chat logic
    5. Store voice message in session history
    6. Clean up temp file
    7. Return transcription + Gemini reply + services

    CRITICAL: temp file cleanup must happen in a finally block
    so it runs even if transcription or Gemini call fails.
    """
    temp_path = None

    try:
        # Step 1: Validate audio format
        validate_audio_file(audio)

        # Step 2: Save to temp file
        temp_path = await save_temp_audio(audio)

        # Step 3: Transcribe with Whisper
        logger.info(
            f"Voice request from session {session_id} "
            f"at ({lat}, {lng})"
        )

        try:
            transcription_result = await transcribe_audio(temp_path, lang)
        except TimeoutError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e),
                headers={"X-Error-Code": "MISSING_PARAMS"}
            )
        except RuntimeError as e:
            raise HTTPException(
                status_code=503,
                detail="Voice transcription service is currently unavailable.",
                headers={"X-Error-Code": "SERVICE_UNAVAILABLE"}
            )

        transcribed_text = transcription_result["text"]
        detected_lang = transcription_result["language"]
        audio_duration = transcription_result["duration_seconds"]

        logger.info(
            f"Transcribed ({audio_duration}s): '{transcribed_text[:100]}'"
        )

        # Step 4: If transcription is empty, return early
        if not transcribed_text or len(transcribed_text.strip()) < 2:
            raise HTTPException(
                status_code=400,
                detail="Could not transcribe audio. "
                       "Please speak clearly and try again.",
                headers={"X-Error-Code": "MISSING_PARAMS"}
            )

        # Step 5: Get or create session
        session = get_or_create_session(session_id, db)

        # Step 6: Append user voice message to history
        # Store with type="voice" so frontend can show mic icon
        append_message(
            session, "user", transcribed_text, "voice", None, db
        )

        # Step 7: Detect language (prefer Whisper's detection over hint)
        # Map Whisper language codes back to our codes
        # Whisper returns full codes like "hi", "en", "pa"
        effective_lang = detected_lang if detected_lang in ["en","hi","pa"] \
                         else lang

        # Step 8: Call Gemini with transcribed text
        gemini_svc = get_gemini_service()
        history = list(session.messages or [])

        try:
            raw_response = await asyncio.to_thread(
                gemini_svc.send_message,
                transcribed_text,
                history[:-1],
                effective_lang
            )
        except Exception as e:
            logger.error(f"Gemini call failed for voice input: {e}")
            raise HTTPException(
                status_code=502,
                detail="AI service is temporarily unavailable.",
                headers={"X-Error-Code": "AI_ERROR"}
            )

        # Step 9: Extract intent
        clean_reply, intent = gemini_svc.extract_intent(raw_response)
        triage_triggered = (intent == "start_triage")

        # Step 10: Fetch services for detected intent
        from schemas.location import get_state_code
        state_code = get_state_code(lat, lng)

        services_data = {}
        if state_code and intent in INTENT_SERVICE_MAP and \
           INTENT_SERVICE_MAP[intent]:
            services_data = await fetch_services_for_intent(
                intent, lat, lng, db, state_code
            )

        # Step 11: Append assistant reply to history
        append_message(
            session, "assistant", raw_response, "text", intent, db
        )

        # Step 12: Update session location
        session.last_location_lat = lat
        session.last_location_lng = lng
        session.lang = effective_lang
        db.commit()

        # Step 13: Build suggested actions
        suggested = build_suggested_actions(intent, services_data)

        return VoiceChatResponse(
            session_id=session_id,
            transcription=transcribed_text,
            transcription_lang=effective_lang,
            reply=ReplyBlock(text=clean_reply, lang=effective_lang),
            intent=intent,
            triage_triggered=triage_triggered,
            services=services_data if services_data else None,
            suggested_actions=suggested,
            audio_duration_seconds=audio_duration
        )

    finally:
        # ALWAYS clean up the temp file — runs even on error/exception
        cleanup_temp_file(temp_path)


@router.get(
    "/chat/session/{session_id}",
    response_model=SessionHistoryResponse
)
def get_session(session_id: str, db = Depends(get_db)):
    """
    Retrieve full chat history for a session.
    Returns 404 if session_id not found.
    Strips INTENT: lines from assistant messages before returning
    (clean display for frontend).
    """
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.is_cleared == False
    ).first()

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
            headers={"X-Error-Code": "SESSION_NOT_FOUND"}
        )

    # Clean INTENT lines from assistant messages for frontend
    clean_messages = []
    for msg in (session.messages or []):
        content = msg.get("content", "")
        if msg.get("role") == "assistant" and "\nINTENT:" in content:
            content = content.split("\nINTENT:")[0].strip()
        clean_messages.append(MessageRecord(
            role=msg["role"],
            content=content,
            timestamp=msg.get("timestamp", ""),
            type=msg.get("type", "text"),
            intent=msg.get("intent")
        ))

    last_location = None
    if session.last_location_lat and session.last_location_lng:
        last_location = LocationInput(
            lat=session.last_location_lat,
            lng=session.last_location_lng
        )

    return SessionHistoryResponse(
        session_id=session_id,
        created_at=session.created_at.isoformat() + "Z",
        messages=clean_messages,
        last_location=last_location
    )


@router.delete(
    "/chat/session/{session_id}",
    response_model=SessionClearResponse
)
def delete_session(session_id: str, db = Depends(get_db)):
    """
    Mark session as cleared (privacy). Does NOT delete the DB row
    (preserves the session_id slot). Sets is_cleared=True,
    clears messages=[].
    Returns 404 if session not found.
    """
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
            headers={"X-Error-Code": "SESSION_NOT_FOUND"}
        )

    session.is_cleared = True
    session.messages = []
    session.updated_at = datetime.utcnow()
    db.commit()

    return SessionClearResponse(
        session_id=session_id,
        cleared=True
    )
