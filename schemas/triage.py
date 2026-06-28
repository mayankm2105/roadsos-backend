from pydantic import BaseModel, Field
from typing import Optional, List, Union


# ── Request schemas ──────────────────────────────────────────

class TriageLocation(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class TriageStartRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    initial_description: str = Field(
        ..., min_length=5, max_length=1000,
        description="User's description of their injuries"
    )
    location: TriageLocation
    lang: str = Field(default="en")


class TriageAnswerRequest(BaseModel):
    triage_id: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1, max_length=500)
    session_id: str = Field(..., min_length=1)


# ── Response schemas ─────────────────────────────────────────

class TriageInProgressResponse(BaseModel):
    triage_id: str
    session_id: str
    status: str = "in_progress"
    current_question: str
    question_index: int       # 1-based (for display: "Question 1 of 5")
    total_questions: int
    severity_score_so_far: Optional[float] = None
    # Show running score so frontend can show a progress bar


class NearestTraumaCentre(BaseModel):
    id: str
    name: str
    phone: Optional[str] = None
    address: str
    distance_m: int
    drive_time_min: Optional[int] = None
    verified_trauma_centre: bool = True
    maps_url: str


class TriageCompletedResponse(BaseModel):
    triage_id: str
    session_id: str
    status: str = "completed"
    severity: str              # "low" | "medium" | "high" | "critical"
    severity_score: float      # 0.0 - 10.0
    recommendation: str        # Human-readable recommendation in user's lang
    auto_stopped: bool         # True if stopped early (critical severity)
    nearest_trauma_centre: Optional[NearestTraumaCentre] = None
    emergency_services: Optional[dict] = None
    # {"ambulance": [top 2], "hospital": [top 2 trauma centres]}
    suggested_actions: List[dict] = []


# Union response type — endpoint returns one or the other
# (use Union[TriageInProgressResponse, TriageCompletedResponse] in endpoint)


# ── Severity constants ───────────────────────────────────────

SEVERITY_LEVELS = {
    "low":      (0.0, 3.0),
    "medium":   (3.0, 6.0),
    "high":     (6.0, 8.0),
    "critical": (8.0, 10.0),
}

CRITICAL_AUTO_STOP_THRESHOLD = 8.0
# If severity_score reaches this, stop asking and escalate immediately

SEVERITY_RECOMMENDATIONS = {
    "en": {
        "low": "✅ Your injuries appear minor. Rest and monitor your "
               "condition. Visit a local clinic if pain persists.",
        "medium": "⚠️ You have moderate injuries. Please visit the nearest "
                  "hospital soon. Avoid driving yourself.",
        "high": "🚨 Your injuries are serious. Call an ambulance (108) "
                "or get someone to take you to a hospital immediately.",
        "critical": "🚨 CRITICAL: Your injuries are life-threatening. "
                    "Call 108 NOW. Do not move unnecessarily. "
                    "Go to the nearest trauma centre immediately."
    },
    "hi": {
        "low": "✅ आपकी चोटें मामूली लगती हैं। आराम करें और स्थिति पर "
               "नज़र रखें। दर्द बना रहे तो पास के क्लीनिक जाएं।",
        "medium": "⚠️ आपको मध्यम चोटें हैं। कृपया जल्द से जल्द नज़दीकी "
                  "अस्पताल जाएं। खुद गाड़ी न चलाएं।",
        "high": "🚨 आपकी चोटें गंभीर हैं। तुरंत एम्बुलेंस बुलाएं (108) "
                "या किसी को अस्पताल ले जाने के लिए कहें।",
        "critical": "🚨 अत्यंत गंभीर: आपकी जान को खतरा है। अभी 108 पर "
                    "कॉल करें। अनावश्यक हिलें नहीं। "
                    "तुरंत नज़दीकी ट्रॉमा सेंटर जाएं।"
    }
}


def get_severity_level(score: float) -> str:
    """Convert a numeric score to a severity level string."""
    if score >= 8.0:
        return "critical"
    elif score >= 6.0:
        return "high"
    elif score >= 3.0:
        return "medium"
    else:
        return "low"


def get_recommendation(severity: str, lang: str) -> str:
    """Get localized recommendation for a severity level."""
    lang_key = lang if lang in SEVERITY_RECOMMENDATIONS else "en"
    return SEVERITY_RECOMMENDATIONS[lang_key].get(
        severity,
        SEVERITY_RECOMMENDATIONS["en"][severity]
    )
