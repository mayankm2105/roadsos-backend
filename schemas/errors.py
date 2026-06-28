from pydantic import BaseModel

class ErrorDetail(BaseModel):
    code: str
    message: str
    fallback_used: bool = False

class ErrorResponse(BaseModel):
    error: ErrorDetail

ERROR_CODES = {
    "INVALID_COORDS": 400,
    "MISSING_PARAMS": 400,
    "SESSION_NOT_FOUND": 404,
    "SOS_NOT_FOUND": 404,
    "PLACES_API_ERROR": 502,
    "AI_ERROR": 502,
    "SERVICE_UNAVAILABLE": 503,
    "RATE_LIMITED": 429,
    "REGION_OUT_OF_SCOPE": 400,
}
