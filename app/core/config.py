"""
BHUMI-NITI: Configuration Settings
"""
import os
from pydantic import BaseModel, Field

class Settings(BaseModel):
    APP_NAME: str = "BHUMI-NITI"
    APP_VERSION: str = "2.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "bhumi-niti-national-governance-secret-key-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 # 24 hours
    
    # Database Settings
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "sqlite:///./bhumi_niti.db" # Default local SQLite fallback; production uses postgresql://...
    )
    
    # Vector Search & RAG Settings
    VECTOR_DIMENSION: int = 384
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

settings = Settings()
