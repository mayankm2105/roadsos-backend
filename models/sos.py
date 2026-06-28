from sqlalchemy import Column, String, Float, DateTime, Text, JSON
from datetime import datetime, timedelta
from database import Base

class SOSLink(Base):
    __tablename__ = "sos_links"

    id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24))
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    address = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    contact_name = Column(String(200), nullable=True)
    contact_phone = Column(String(20), nullable=True)
    state_code = Column(String(5), nullable=True)
    status = Column(String(20), default="active")
    nearby_services = Column(JSON, nullable=True)
    whatsapp_url = Column(String(500), nullable=True)
