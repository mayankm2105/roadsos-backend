from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import datetime


class CacheRegion(BaseModel):
    country: str = "IN"
    state: str                        # "HR" or "DL"


class StateVersionInfo(BaseModel):
    last_updated: datetime
    version: str                      # "YYYYMMDD" string
    entries_count: int = 0


class OfflineCacheResponse(BaseModel):
    region: CacheRegion
    total_pincodes: int               # distinct pincodes in this state's cache
    last_updated: datetime
    entries_count: int                # total rows returned
    data: Dict[str, List[Dict[str, Any]]]
    # keys: "police", "hospital", "ambulance", "towing", "mechanic"


class CacheLastUpdatedResponse(BaseModel):
    country: str = "IN"
    states: Dict[str, StateVersionInfo]
    # keys: "HR", "DL"


class CacheSyncRequest(BaseModel):
    admin_key: str
    states: List[str] = ["HR", "DL"]  # which states to refresh


class CacheSyncResponse(BaseModel):
    job_id: str
    status: str = "queued"            # always "queued" — stub for hackathon
    states: List[str]
    message: str
