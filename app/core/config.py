"""
BHUMI-NITI: Configuration Settings
"""
import os
from pydantic import BaseModel, field_validator, model_validator
from dotenv import load_dotenv

load_dotenv()

UNSAFE_SECRET_VALUES = {
    "", "secret", "change-me", "changeme", "dev-secret", "test-secret",
    "bhumi-niti-national-governance-secret-key-2026",
    "dev-secret-key-change-me-please-2026-9a1b2c3d",
}


def _default_secret() -> str:
    """Provide a development-only fallback secret while enforcing a production requirement."""
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        return ""
    return "dev-secret-key-change-me-please-2026-9a1b2c3d"


class Settings(BaseModel):
    APP_NAME: str = "BHUMI-NITI"
    APP_VERSION: str = "2.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    SECRET_KEY: str = os.getenv("SECRET_KEY") or _default_secret()
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", "bhuminiti")
    JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "bhuminiti-api")
    BOOTSTRAP_ADMIN_EMAIL: str = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "officer@bhuminiti.gov.in")
    BOOTSTRAP_ADMIN_PASSWORD: str = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "SecurePassword2026!")

    # Database Settings
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        os.getenv("POSTGRES_URL", "sqlite:///./bhumi_niti.db"),  # SQLite is local development/test only
    )

    # Vector Search & RAG Settings
    VECTOR_DIMENSION: int = 1536
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-004")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    @model_validator(mode="after")
    def validate_production_settings(self):
        if self.ENVIRONMENT.lower() == "production":
            if not self.DATABASE_URL.startswith(("postgres://", "postgresql://")):
                raise ValueError("Production requires DATABASE_URL to point to PostgreSQL.")
            if self.DEMO_MODE:
                raise ValueError("DEMO_MODE must be disabled in production.")
            if self.BOOTSTRAP_ADMIN_PASSWORD == "SecurePassword2026!":
                raise ValueError("Set BOOTSTRAP_ADMIN_PASSWORD explicitly in production.")
        return self

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str, info):
        environment = (info.data.get("ENVIRONMENT") or os.getenv("ENVIRONMENT", "development")).lower()
        if environment == "production" and not value:
            raise ValueError("SECRET_KEY is required in production. Set it explicitly in the environment.")
        if value in UNSAFE_SECRET_VALUES:
            raise ValueError("SECRET_KEY is still using an unsafe development value; set a unique secret.")
        return value


settings = Settings()
