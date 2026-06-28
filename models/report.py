from sqlalchemy import Column, String, Float, DateTime, Text, JSON, ForeignKey, Integer
from datetime import datetime
import uuid
from database import Base

class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident_date = Column(String(100), nullable=True)
    incident_location = Column(String(500), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    vehicles_involved = Column(JSON, nullable=True)
    injuries_count = Column(Integer, nullable=True)
    witness_details = Column(Text, nullable=True)
    nearest_police_station = Column(String(500), nullable=True)
    reporting_person_name = Column(String(200), nullable=True)
    reporting_person_phone = Column(String(20), nullable=True)
    fir_json = Column(JSON, nullable=True)
    download_text = Column(Text, nullable=True)
    whatsapp_url = Column(String(500), nullable=True)
    lang = Column(String(5), default="en")
