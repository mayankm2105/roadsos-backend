from pydantic import BaseModel, Field
from typing import Optional, List


class ReverseGeocodeResponse(BaseModel):
    lat: float
    lng: float
    address: str                  # Full formatted address
    pincode: Optional[str] = None # 6-digit Indian pincode
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None   # "Haryana" | "Delhi" | etc.
    state_code: Optional[str] = None  # "HR" | "DL" | None
    country: str = "IN"
    data_source: str = "google"   # "google" | "nominatim" | "cache"


class GeoSearchResult(BaseModel):
    address: str
    lat: float
    lng: float
    place_id: Optional[str] = None  # Google place_id if available
    pincode: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    within_coverage: bool = False   # True if within HR/DL bounds


class GeoSearchResponse(BaseModel):
    query: str
    results: List[GeoSearchResult]
    data_source: str = "google"     # "google" | "nominatim" | "cache"
