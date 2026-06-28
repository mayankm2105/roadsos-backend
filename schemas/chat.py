from pydantic import BaseModel, Field
from typing import Optional, List

class LocationInput(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)

class ChatMessageRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=2000)
    location: LocationInput
    lang: str = Field(default="en")
    # lang hint: "en" | "hi" | "pa" | "hw"

class SuggestedAction(BaseModel):
    label: str           # e.g. "Call 108 (Ambulance)"
    action: str          # "call" | "sos_share" | "triage" | "navigate"
    value: Optional[str] = None  # phone number, URL, or null

class ReplyBlock(BaseModel):
    text: str
    lang: str  # detected/used language

class ChatMessageResponse(BaseModel):
    session_id: str
    reply: ReplyBlock
    intent: Optional[str] = None
    triage_triggered: bool = False
    services: Optional[dict] = None
    suggested_actions: List[SuggestedAction] = []

class VoiceChatResponse(BaseModel):
    session_id: str
    transcription: str
    transcription_lang: str
    reply: ReplyBlock
    intent: Optional[str] = None
    triage_triggered: bool = False
    services: Optional[dict] = None
    suggested_actions: List[SuggestedAction] = []
    audio_duration_seconds: Optional[float] = None

class MessageRecord(BaseModel):
    role: str           # "user" | "assistant"
    content: str
    timestamp: str      # ISO datetime string
    type: str = "text"  # "text" | "voice"
    intent: Optional[str] = None   # only on assistant messages

class SessionHistoryResponse(BaseModel):
    session_id: str
    created_at: str
    messages: List[MessageRecord]
    last_location: Optional[LocationInput] = None

class SessionClearResponse(BaseModel):
    session_id: str
    cleared: bool

INTENT_SERVICE_MAP = {
    "find_ambulance":        ["ambulance"],
    "find_police":           ["police"],
    "find_hospital":         ["hospital"],
    "find_towing":           ["towing"],
    "find_mechanic":         ["mechanic"],
    "find_ambulance_police": ["ambulance", "police"],
    "start_triage":          [],   # triggers triage flow, no service fetch
    "sos_share":             [],   # triggers SOS creation suggestion
    "general_help":          [],   # no service fetch needed
    "none":                  [],   # chitchat / unclear
}

def build_suggested_actions(intent: str, services: dict) -> List[SuggestedAction]:
    """
    Build context-aware suggested actions based on detected intent.
    Rules:
    - Always include "Start health check" triage action if any injury mentioned
    - If ambulance in services: add "Call 108 (Ambulance)" → action="call" value="108"
    - If police in services: add "Call 100 (Police)" → action="call" value="100"
    - Always add "Share my location" → action="sos_share" value=None
    - If hospital in services: add "Navigate to nearest hospital" →
        action="navigate" value=maps_url of first result
    """
    actions = []
    if "ambulance" in (services or {}):
        actions.append(SuggestedAction(
            label="Call 108 (Ambulance)",
            action="call",
            value="108"
        ))
    if "police" in (services or {}):
        actions.append(SuggestedAction(
            label="Call 100 (Police)",
            action="call",
            value="100"
        ))
    if "hospital" in (services or {}):
        hospital_list = services.get("hospital", [])
        if hospital_list:
            first = hospital_list[0]
            maps_url = first.get("maps_url") if isinstance(first, dict) \
                       else getattr(first, "maps_url", None)
            actions.append(SuggestedAction(
                label="Navigate to nearest hospital",
                action="navigate",
                value=maps_url
            ))
    actions.append(SuggestedAction(
        label="Share my location",
        action="sos_share",
        value=None
    ))
    if intent not in ["start_triage", "none"]:
        actions.append(SuggestedAction(
            label="Start health check",
            action="triage",
            value=None
        ))
    return actions
