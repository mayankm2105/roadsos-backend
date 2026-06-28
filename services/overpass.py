import httpx
from typing import List, Dict, Any
from utils.logger import get_logger

logger = get_logger(__name__)

CATEGORY_OSM_TAGS = {
    "police": 'amenity"="police"',
    "hospital": 'amenity"="hospital"',
    "ambulance": 'amenity"="ambulance_station"',
    "towing": 'shop"="car_repair"',
    "mechanic": 'shop"="tyres"'
}

async def search_nearby(category: str, lat: float, lng: float, radius: int = 5000, limit: int = 10) -> List[Dict[str, Any]]:
    osm_tag = CATEGORY_OSM_TAGS.get(category)
    if not osm_tag:
        return []

    query = f"""
    [out:json][timeout:10];
    (
      node[{osm_tag}](around:{radius},{lat},{lng});
      way[{osm_tag}](around:{radius},{lat},{lng});
    );
    out body center {limit};
    """
    
    url = "https://overpass-api.de/api/interpreter"
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, data={"data": query})
            response.raise_for_status()
            data = response.json()
            
            elements = data.get("elements", [])
            if not elements:
                return []
                
            parsed_results = []
            for element in elements:
                el_type = element.get("type")
                
                if el_type == "node":
                    el_lat = element.get("lat")
                    el_lng = element.get("lon")
                elif el_type == "way":
                    center = element.get("center", {})
                    el_lat = center.get("lat")
                    el_lng = center.get("lon")
                else:
                    continue
                    
                tags = element.get("tags", {})
                
                parts = [
                    tags.get("addr:housenumber", ""),
                    tags.get("addr:street", ""),
                    tags.get("addr:city", ""),
                    tags.get("addr:state", "")
                ]
                address = " ".join(p for p in parts if p).strip()
                if not address:
                    address = "Address not available"
                    
                phone = tags.get("phone") or tags.get("contact:phone")
                
                parsed_results.append({
                    "id": f"osm_{el_type}_{element.get('id')}",
                    "name": tags.get("name", "Unknown"),
                    "address": address,
                    "lat": el_lat,
                    "lng": el_lng,
                    "phone": phone,
                    "open_now": None,
                    "rating": None
                })
                
            return parsed_results
            
    except httpx.TimeoutException as e:
        logger.warning(f"Overpass API timed out for {category} at {lat},{lng}: {e}")
        raise TimeoutError("Overpass API timed out")
    except Exception as e:
        logger.warning(f"Overpass API unavailable for {category} at {lat},{lng}: {e}")
        raise Exception("Overpass API unavailable")
