from sqlalchemy import Column, String, Float, DateTime, Boolean, JSON
from datetime import datetime
import uuid
from database import Base

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    messages = Column(JSON, default=list)
    last_location_lat = Column(Float, nullable=True)
    last_location_lng = Column(Float, nullable=True)
    lang = Column(String(5), default="en")
    is_cleared = Column(Boolean, default=False)
