from pydantic_settings import BaseSettings
from typing import List
from pydantic import ConfigDict

class Settings(BaseSettings):
    # ── Add these new fields ───────────────────────────────────────────
    ENVIRONMENT: str = "development"      # "development" | "production"
    VERSION: str = "2.0.0"               # Used in X-RoadSoS-Version header
    
    # CORS_ORIGINS stored as comma-separated string in .env,
    # split into list for FastAPI middleware
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        """Split CORS_ORIGINS env var into a Python list."""
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    # Google APIs
    GOOGLE_PLACES_API_KEY: str = ""
    GOOGLE_GEOCODING_API_KEY: str = ""

    # Gemini AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # Whisper STT
    STT_PROVIDER: str = "whisper"
    WHISPER_MODEL: str = "base"

    # SQLite
    SQLITE_DB_PATH: str = "./data/roadsos_cache.db"
    CACHE_COVERAGE_STATES: str = "HR,DL"

    # SOS
    SOS_BASE_URL: str = "https://roadsos.vercel.app/sos/"
    SOS_LINK_TTL_HOURS: int = 24

    # Admin
    ADMIN_KEY: str = "roadsos-admin-2026"

    # App
    CACHE_TTL_HOURS: int = 24
    LOG_LEVEL: str = "INFO"
    APP_VERSION: str = "2.0.0"

    model_config = ConfigDict(env_file=".env", extra="ignore")

settings = Settings()
