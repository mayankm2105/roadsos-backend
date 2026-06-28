from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class ServiceResult(BaseModel):
    id: str
    name: str
    phone: Optional[str] = None
    address: str
    lat: float
    lng: float
    distance_m: int
    drive_time_min: Optional[int] = None
    open_now: Optional[bool] = None
    rating: Optional[float] = None
    maps_url: str
    source: str  # "google_places" | "overpass" | "cache"
    state: str   # "HR" | "DL"

class HospitalResult(ServiceResult):
    has_emergency: bool = True
    verified_trauma_centre: bool = False
    trauma_verification_method: Optional[str] = None
    # "curated_list" | "keyword_match" | None
    bed_type: Optional[str] = None  # "government" | "private"

class AmbulanceResult(ServiceResult):
    ambulance_type: str = "government"  # "government" | "private"
    national_helpline: str = "108"
    response_time_est_min: Optional[int] = None

class TowingResult(ServiceResult):
    service_type: str = "towing"
    vehicle_types: List[str] = ["car", "bike", "truck"]
    is_24x7: bool = False

class MechanicResult(ServiceResult):
    service_subtype: Optional[str] = None
    # "puncture" | "breakdown" | "fuel" | "general"

class ServiceListResponse(BaseModel):
    category: str
    data_source: str  # "google_places" | "overpass" | "cache"
    count: int
    results: List[ServiceResult]
    fetched_at: str  # ISO datetime string

class HospitalListResponse(BaseModel):
    category: str = "hospital"
    data_source: str
    count: int
    results: List[HospitalResult]
    fetched_at: str

class AmbulanceListResponse(BaseModel):
    category: str = "ambulance"
    data_source: str
    count: int
    results: List[AmbulanceResult]
    national_helplines: dict  # hardcoded helplines dict
    fetched_at: str

class TowingListResponse(BaseModel):
    category: str = "towing"
    data_source: str
    count: int
    results: List[TowingResult]
    fetched_at: str

class MechanicListResponse(BaseModel):
    category: str = "mechanic"
    data_source: str
    count: int
    results: List[MechanicResult]
    fetched_at: str

class NearbyLocationInfo(BaseModel):
    lat: float
    lng: float
    address: Optional[str] = None
    pincode: Optional[str] = None
    state: Optional[str] = None

class NearbyResults(BaseModel):
    police: List[ServiceResult] = []
    hospital: List[HospitalResult] = []
    ambulance: List[AmbulanceResult] = []
    towing: List[TowingResult] = []
    mechanic: List[MechanicResult] = []

class NearbyResponse(BaseModel):
    location: NearbyLocationInfo
    data_source: str
    results: NearbyResults
    fetched_at: str

NATIONAL_HELPLINES = {
    "ambulance": "108",
    "police": "100",
    "fire": "101",
    "women_helpline": "1091",
    "mental_health": "1925",
    "road_accident_relief": "1073"
}

TRAUMA_KEYWORDS = [
    "trauma", "aiims", "pgi", "pgims", "safdarjung", "rml",
    "apollo", "fortis", "max", "medanta", "sir ganga ram"
]
