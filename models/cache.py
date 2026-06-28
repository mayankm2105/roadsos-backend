from sqlalchemy import Column, String, Integer, DateTime, JSON
from datetime import datetime, timedelta
from database import Base

class CacheEntry(Base):
    __tablename__ = "cache_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key = Column(String(500), unique=True, index=True)
    category = Column(String(50))
    pincode = Column(String(10), nullable=True, index=True)
    state_code = Column(String(5))
    data = Column(JSON)
    data_source = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24))
    version = Column(String(20))
    hit_count = Column(Integer, default=0)
