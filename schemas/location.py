from pydantic import BaseModel, Field
from typing import Optional

class LocationInput(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")

class LocationWithAddress(LocationInput):
    address: Optional[str] = None
    pincode: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None  # "HR" or "DL"
    country: str = "IN"

HARYANA_BOUNDS = {
    "lat_min": 27.65, "lat_max": 30.90,
    "lng_min": 74.45, "lng_max": 77.60
}

DELHI_BOUNDS = {
    "lat_min": 28.40, "lat_max": 28.88,
    "lng_min": 76.84, "lng_max": 77.35
}

def is_within_coverage(lat: float, lng: float) -> bool:
    """Returns True if coordinates are within Haryana or Delhi bounding boxes."""
    in_haryana = (
        HARYANA_BOUNDS["lat_min"] <= lat <= HARYANA_BOUNDS["lat_max"] and
        HARYANA_BOUNDS["lng_min"] <= lng <= HARYANA_BOUNDS["lng_max"]
    )
    in_delhi = (
        DELHI_BOUNDS["lat_min"] <= lat <= DELHI_BOUNDS["lat_max"] and
        DELHI_BOUNDS["lng_min"] <= lng <= DELHI_BOUNDS["lng_max"]
    )
    return in_haryana or in_delhi

def get_state_code(lat: float, lng: float) -> Optional[str]:
    """Returns 'HR', 'DL', or None if out of coverage."""
    if (DELHI_BOUNDS["lat_min"] <= lat <= DELHI_BOUNDS["lat_max"] and
            DELHI_BOUNDS["lng_min"] <= lng <= DELHI_BOUNDS["lng_max"]):
        return "DL"
    if (HARYANA_BOUNDS["lat_min"] <= lat <= HARYANA_BOUNDS["lat_max"] and
            HARYANA_BOUNDS["lng_min"] <= lng <= HARYANA_BOUNDS["lng_max"]):
        return "HR"
    return None
