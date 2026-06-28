from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from config import settings
from utils.logger import get_logger
import os

logger = get_logger(__name__)

# Ensure directory exists for sqlite db
os.makedirs(os.path.dirname(settings.SQLITE_DB_PATH.replace("sqlite:///", "")), exist_ok=True)

# Format the path for SQLAlchemy
db_url = f"sqlite:///{settings.SQLITE_DB_PATH}" if not settings.SQLITE_DB_PATH.startswith("sqlite") else settings.SQLITE_DB_PATH

engine = create_engine(
    db_url, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from models.triage import TriageSession  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database initialized at {settings.SQLITE_DB_PATH}")
