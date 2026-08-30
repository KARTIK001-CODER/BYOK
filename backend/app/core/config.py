from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App Info
    APP_NAME: str = "RAGForge"
    APP_ENV: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = False
    VERSION: str = "0.4.0"

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    API_V1_STR: str = "/api/v1"
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # Database Settings (Neon PostgreSQL / Local Postgres)
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ragforge"
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # Security & Auth Settings
    JWT_SECRET_KEY: str = Field(
        default="change-this-to-a-super-secret-hex-key-minimum-32-chars-for-dev"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Object Storage & Upload Settings
    STORAGE_BACKEND: Literal["local", "s3", "r2", "gcs"] = "local"
    STORAGE_LOCAL_DIR: str = "data/storage"
    MAX_UPLOAD_SIZE_MB: int = 25

    # Document Ingestion & Chunking Settings
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    MAX_EXTRACTED_TEXT_CHARS: int = 5000000
    MAX_CHUNKS_PER_DOCUMENT: int = 10000

    # BYOK Master Encryption Key Placeholder (Deferred to Future Phases)
    API_KEY_ENCRYPTION_KEY: str = Field(
        default="change-this-to-a-32-byte-hex-key-for-byok-encryption-vault"
    )

    # Logging Settings
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["text", "json"] = "text"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def validate_chunking_config(self) -> "Settings":
        if self.CHUNK_SIZE <= 0:
            raise ValueError("CHUNK_SIZE must be greater than 0")
        if self.CHUNK_OVERLAP < 0:
            raise ValueError("CHUNK_OVERLAP must be non-negative")
        if self.CHUNK_OVERLAP >= self.CHUNK_SIZE:
            raise ValueError("CHUNK_OVERLAP must be strictly less than CHUNK_SIZE")
        if self.MAX_EXTRACTED_TEXT_CHARS <= 0:
            raise ValueError("MAX_EXTRACTED_TEXT_CHARS must be greater than 0")
        if self.MAX_CHUNKS_PER_DOCUMENT <= 0:
            raise ValueError("MAX_CHUNKS_PER_DOCUMENT must be greater than 0")
        return self

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Singleton getter for cached application settings."""
    return Settings()
