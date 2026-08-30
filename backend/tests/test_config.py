from app.core.config import Settings


def test_settings_default_values() -> None:
    """Verify default settings values."""
    settings = Settings(
        APP_ENV="development",
        APP_NAME="RAGForge",
        DEBUG=True,
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ragforge",
    )
    assert settings.APP_NAME == "RAGForge"
    assert settings.APP_ENV == "development"
    assert settings.DEBUG is True
    assert settings.API_V1_STR == "/api/v1"
    assert "postgresql+asyncpg://" in settings.DATABASE_URL


def test_cors_origins_string_parsing() -> None:
    """Verify comma-separated string parsing for CORS origins."""
    settings = Settings(
        CORS_ORIGINS="http://localhost:3000,http://example.com, https://ragforge.ai",
    )
    assert settings.CORS_ORIGINS == [
        "http://localhost:3000",
        "http://example.com",
        "https://ragforge.ai",
    ]


def test_cors_origins_list() -> None:
    """Verify list format for CORS origins."""
    origins = ["http://localhost:3000", "http://localhost:5173"]
    settings = Settings(CORS_ORIGINS=origins)
    assert origins == settings.CORS_ORIGINS
