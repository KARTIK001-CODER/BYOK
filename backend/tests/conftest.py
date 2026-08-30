from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app


def get_test_settings() -> Settings:
    """Return test-specific settings."""
    return Settings(
        APP_ENV="testing",
        APP_NAME="RAGForge-Test",
        DEBUG=True,
        LOG_LEVEL="DEBUG",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        CORS_ORIGINS=["http://testserver", "http://localhost:3000"],
    )


@pytest.fixture(autouse=True)
def override_settings() -> None:
    """Override application settings with test settings for all tests."""
    test_settings = get_test_settings()
    app.dependency_overrides[get_settings] = lambda: test_settings


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Mock database session that simulates successful health checks."""
    mock_session = AsyncMock(spec=AsyncSession)
    # Simulate SELECT 1 returning 1
    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar.return_value = 1
    mock_session.execute.return_value = mock_scalar_result
    # Mock dialect name
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_session.bind = mock_bind
    return mock_session


@pytest.fixture
async def client(mock_db_session: AsyncMock) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing API endpoints."""
    # Override database dependency with mock
    app.dependency_overrides[get_db] = lambda: mock_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    # Clean up overrides
    app.dependency_overrides.clear()
