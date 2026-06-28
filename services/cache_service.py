from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models.cache import CacheEntry
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

def get_cache_key(category: str, lat: float, lng: float, radius: int) -> str:
    """Round lat/lng to 2 decimal places to group nearby queries."""
    return f"{category}:{round(lat, 2)}:{round(lng, 2)}:{radius}"

def get_cached_results(db: Session, cache_key: str) -> Optional[List[Dict[str, Any]]]:
    """Query CacheEntry where cache_key matches AND expires_at > now()."""
    entry = db.query(CacheEntry).filter(
        CacheEntry.cache_key == cache_key,
        CacheEntry.expires_at > datetime.utcnow()
    ).first()
    
    if entry:
        entry.hit_count += 1
        db.commit()
        return entry.data
    return None

def save_to_cache(db: Session, cache_key: str, category: str, data: List[Dict[str, Any]], data_source: str, state_code: str) -> None:
    """Upsert CacheEntry."""
    entry = db.query(CacheEntry).filter(CacheEntry.cache_key == cache_key).first()
    
    version = datetime.utcnow().strftime("%Y%m%d")
    expires_at = datetime.utcnow() + timedelta(hours=settings.CACHE_TTL_HOURS)
    
    if entry:
        entry.data = data
        entry.data_source = data_source
        entry.state_code = state_code
        entry.expires_at = expires_at
        entry.version = version
        entry.hit_count = 0
    else:
        new_entry = CacheEntry(
            cache_key=cache_key,
            category=category,
            data=data,
            data_source=data_source,
            state_code=state_code,
            expires_at=expires_at,
            version=version,
            hit_count=0
        )
        db.add(new_entry)
        
    db.commit()
    logger.debug(f"Saved to cache for {cache_key}")

def get_cached_by_state(db: Session, category: str, state_code: str) -> List[Dict[str, Any]]:
    """Query all non-expired CacheEntries for a category + state."""
    entries = db.query(CacheEntry).filter(
        CacheEntry.category == category,
        CacheEntry.state_code == state_code,
        CacheEntry.expires_at > datetime.utcnow()
    ).all()
    
    combined_data = []
    seen_ids = set()
    for entry in entries:
        for item in entry.data:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                combined_data.append(item)
                
    return combined_data
