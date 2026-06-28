import math

def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Calculate straight-line distance in metres between two GPS coordinates."""
    R = 6371000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    return int(round(distance))

def estimate_drive_time(distance_m: int) -> int:
    """Estimate drive time in minutes assuming average speed of 30 km/h in India."""
    # (distance_m / 1000) / 30 * 60 = (distance_m / 1000) * 2 = distance_m / 500
    minutes = (distance_m / 1000) / 30 * 60
    return max(1, math.ceil(minutes))

def build_maps_url(lat: float, lng: float, place_id: str = None) -> str:
    """Return Google Maps URL for the location."""
    if place_id:
        return f"https://maps.google.com/?cid={place_id}"
    else:
        return f"https://maps.google.com/?q={lat},{lng}"
