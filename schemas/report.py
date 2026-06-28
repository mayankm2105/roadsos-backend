from pydantic import BaseModel, Field
from typing import Optional, List


# ── Request schemas ──────────────────────────────────────────

class AdditionalReportInfo(BaseModel):
    """
    Optional structured details the user provides at report generation time.
    All fields are optional — Gemini will infer from chat if not provided.
    """
    vehicle_numbers: List[str] = Field(
        default=[],
        description="Vehicle registration numbers e.g. ['HR26AB1234']"
    )
    witnesses: int = Field(
        default=0,
        ge=0, le=50,
        description="Estimated number of witnesses present"
    )
    injuries_count: int = Field(
        default=0,
        ge=0,
        description="Number of injured persons"
    )
    accident_time: Optional[str] = Field(
        default=None,
        description="ISO datetime of accident e.g. 2026-06-15T09:15:00+05:30"
    )
    accident_type: Optional[str] = Field(
        default=None,
        description="Type: two_wheeler_collision | four_wheeler | "
                    "pedestrian | multi_vehicle | hit_and_run | other"
    )
    reporting_person_name: Optional[str] = Field(
        default=None,
        max_length=200
    )
    reporting_person_phone: Optional[str] = Field(
        default=None,
        max_length=20
    )


class ReportGenerateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    additional_info: AdditionalReportInfo = Field(
        default_factory=AdditionalReportInfo
    )
    lang: str = Field(
        default="en",
        description="Language for FIR: en | hi"
    )


# ── FIR draft structure ──────────────────────────────────────

class FIRDraft(BaseModel):
    """
    Structured FIR fields. All fields are Optional because Gemini
    may not have enough context to fill every field — that is okay.
    Unfilled fields appear as null in JSON and are omitted in plain text.
    """
    incident_date: Optional[str] = None
    # Format: "YYYY-MM-DD" e.g. "2026-06-15"

    incident_time: Optional[str] = None
    # Format: "HH:MM AM/PM" e.g. "09:15 AM"

    location: Optional[str] = None
    # Human-readable: "NH44, near Panipat Toll, Haryana - 132103"

    coordinates: Optional[str] = None
    # "28.6139°N, 77.2090°E"

    accident_type: Optional[str] = None
    # "Two-wheeler collision" or as described

    description: Optional[str] = None
    # 2-4 sentence factual description of the accident

    vehicles_involved: List[str] = []
    # ["HR26AB1234", "DL3CAB9876"]

    injuries: Optional[str] = None
    # "1 person with possible chest injury"

    injuries_count: Optional[int] = None

    witnesses: Optional[str] = None
    # "Approximately 2 bystanders present"

    reporting_person: Optional[str] = None
    # Name or "Anonymous" if not provided

    contact: Optional[str] = None
    # Phone or "Available via RoadSoS emergency response"

    nearest_police_station: Optional[str] = None
    # "Panipat City Police Station, +91-180-2637400"

    notes: Optional[str] = None
    # Any additional relevant details Gemini extracts from chat


# ── Response schemas ─────────────────────────────────────────

class ReportGenerateResponse(BaseModel):
    report_id: str
    session_id: str
    generated_at: str               # ISO datetime string
    lang: str
    fir_draft: FIRDraft
    download_text: str              # Plain-text FIR for copy/download
    share_whatsapp_url: str         # Pre-filled WhatsApp share URL


# ── Accident type display names ──────────────────────────────

ACCIDENT_TYPE_LABELS = {
    "en": {
        "two_wheeler_collision": "Two-Wheeler Collision",
        "four_wheeler": "Four-Wheeler Accident",
        "pedestrian": "Pedestrian Accident",
        "multi_vehicle": "Multi-Vehicle Collision",
        "hit_and_run": "Hit and Run",
        "other": "Road Traffic Accident"
    },
    "hi": {
        "two_wheeler_collision": "दोपहिया वाहन टक्कर",
        "four_wheeler": "चारपहिया वाहन दुर्घटना",
        "pedestrian": "पैदल यात्री दुर्घटना",
        "multi_vehicle": "बहु-वाहन टक्कर",
        "hit_and_run": "हिट एंड रन",
        "other": "सड़क यातायात दुर्घटना"
    }
}
