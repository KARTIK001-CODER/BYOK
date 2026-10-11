from app.core.config import Settings


def test_settings_default_values() -> None:
    """Verify default settings values."""
    settings = Settings(
        APP_ENV="development",
        APP_NAME="TracePilot",
        DEBUG=True,
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/tracepilot",
    )
    assert settings.APP_NAME == "TracePilot"
    assert settings.APP_ENV == "development"
    assert settings.DEBUG is True
    assert settings.API_V1_STR == "/api/v1"
    assert "postgresql+asyncpg://" in settings.DATABASE_URL


def test_cors_origins_string_parsing() -> None:
    """Verify comma-separated string parsing for CORS origins."""
    settings = Settings(
        CORS_ORIGINS="http://localhost:3000,http://example.com, https://staging.tracepilot.internal",
    )
    assert settings.CORS_ORIGINS == [
        "http://localhost:3000",
        "http://example.com",
        "https://staging.tracepilot.internal",
    ]


def test_cors_origins_list() -> None:
    """Verify list format for CORS origins."""
    origins = ["http://localhost:3000", "http://localhost:5173"]
    settings = Settings(CORS_ORIGINS=origins)
    assert origins == settings.CORS_ORIGINS


import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_cors_origin_enforcement(client: AsyncClient) -> None:
    """Verify approved origin receives CORS header and unapproved origin is rejected."""
    # Approved origin receives Access-Control-Allow-Origin
    resp_approved = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp_approved.status_code == 200
    assert resp_approved.headers.get("access-control-allow-origin") == "http://localhost:3000"

    # Unapproved origin does not receive Access-Control-Allow-Origin header
    resp_unapproved = await client.get("/health", headers={"Origin": "https://malicious-attacker.evil"})
    assert resp_unapproved.status_code == 200
    assert "access-control-allow-origin" not in resp_unapproved.headers
