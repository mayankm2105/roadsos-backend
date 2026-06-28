from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


# ── Shared sub-schemas ───────────────────────────────────────

class SOSLocation(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class EmergencyContact(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=7, max_length=20)


# ── Request schemas ──────────────────────────────────────────

class SOSCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    location: SOSLocation
    emergency_contacts: List[EmergencyContact] = Field(
        default=[],
        max_length=5,
        description="Up to 5 emergency contacts to notify via WhatsApp"
    )
    severity: str = Field(
        default="high",
        description="Severity level: low | medium | high | critical"
    )
    additional_info: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Extra accident details: vehicle numbers, injury type etc."
    )

    @field_validator("severity", mode="before")
    def validate_severity(cls, v):
        valid = {"low", "medium", "high", "critical"}
        if v not in valid:
            return "high"  # safe default
        return v


class SOSResolveRequest(BaseModel):
    resolved_by: str = Field(
        default="family_member",
        description="Who resolved: family_member | first_responder | self"
    )


# ── Response schemas ─────────────────────────────────────────

class SOSCreateResponse(BaseModel):
    sos_id: str
    shareable_link: str
    whatsapp_link: str               # Generic share link (no specific contact)
    contact_whatsapp_links: List[dict] = []
    # [{"name": "Mom", "phone": "...", "whatsapp_url": "..."}]
    expires_at: str                  # ISO datetime string
    ttl_hours: int = 24


class AccidentLocation(BaseModel):
    lat: float
    lng: float
    address: Optional[str] = None
    pincode: Optional[str] = None
    state: Optional[str] = None


class SOSViewResponse(BaseModel):
    sos_id: str
    status: str                      # "active" | "resolved" | "expired"
    accident_location: AccidentLocation
    created_at: str
    severity: str
    additional_info: Optional[str] = None
    nearest_services: dict           # {ambulance: [...], hospital: [...], police: [...]}


class SOSResolveResponse(BaseModel):
    sos_id: str
    status: str = "resolved"
    resolved_at: str


class SOSExpiredError(BaseModel):
    error: dict
