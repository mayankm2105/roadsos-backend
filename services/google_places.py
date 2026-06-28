import httpx
from typing import Optional, List, Dict, Any
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

CATEGORY_KEYWORDS = {
    "police": "police station",
    "hospital": "hospital",
    "ambulance": "ambulance service",
    "towing": "vehicle towing service",
    "mechanic": "car mechanic puncture shop"
}

async def search_nearby(category: str, lat: float, lng: float, radius: int = 5000, limit: int = 10) -> List[Dict[str, Any]]:
    if not settings.GOOGLE_PLACES_API_KEY:
        raise ValueError("Google Places API key not configured")

    keyword = CATEGORY_KEYWORDS.get(category)
    if not keyword:
        return []

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "keyword": keyword,
        "key": settings.GOOGLE_PLACES_API_KEY
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ZERO_RESULTS":
                return []
            
            if data.get("status") in ["REQUEST_DENIED", "INVALID_REQUEST"]:
                raise Exception(data.get("error_message", "Google Places API error"))
            
            results = data.get("results", [])[:limit]
            
            parsed_results = []
            for result in results:
                parsed_results.append({
                    "id": result.get("place_id"),
                    "name": result.get("name"),
                    "address": result.get("vicinity", ""),
                    "lat": result["geometry"]["location"]["lat"],
                    "lng": result["geometry"]["location"]["lng"],
                    "open_now": result.get("opening_hours", {}).get("open_now", None),
                    "rating": result.get("rating", None),
                    "phone": None
                })
            
            return parsed_results
            
    except Exception as e:
        logger.warning(f"Google Places failed for {category} at {lat},{lng}: {e}")
        raise

async def get_place_phone(place_id: str) -> Optional[str]:
    if not settings.GOOGLE_PLACES_API_KEY:
        return None
        
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "formatted_phone_number",
        "key": settings.GOOGLE_PLACES_API_KEY
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("result", {}).get("formatted_phone_number")
    except Exception as e:
        logger.warning(f"Failed to get phone for place {place_id}: {e}")
        return None
