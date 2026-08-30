from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app


@pytest.mark.asyncio
async def test_root_liveness_check(client: AsyncClient) -> None:
    """Verify that root /health returns 200 OK without database interaction."""
    response = await client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data == {"status": "ok"}
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_api_v1_liveness_check(client: AsyncClient) -> None:
    """Verify that /api/v1/health returns 200 OK."""
    response = await client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_root_readiness_check_success(client: AsyncClient) -> None:
    """Verify that /ready returns ready when database and pgvector are healthy."""
    response = await client.get("/ready")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "ok"
    assert data["vector_store"] == "ok"


@pytest.mark.asyncio
async def test_root_readiness_check_db_failure(client: AsyncClient) -> None:
    """Verify that /ready returns 503 when database query fails."""
    failing_db = AsyncMock(spec=AsyncSession)
    failing_db.execute.side_effect = Exception("Connection refused")
    app.dependency_overrides[get_db] = lambda: failing_db

    response = await client.get("/ready")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["database"] == "error"
    assert data["vector_store"] == "error"


@pytest.mark.asyncio
async def test_root_readiness_check_pgvector_disabled(client: AsyncClient) -> None:
    """Verify that /ready returns 503 when pgvector extension is missing in PostgreSQL."""
    db_no_pgvector = AsyncMock(spec=AsyncSession)
    mock_db_res = MagicMock()
    mock_db_res.scalar.return_value = 1
    mock_vec_res = MagicMock()
    mock_vec_res.scalar.return_value = None

    db_no_pgvector.execute.side_effect = [mock_db_res, mock_vec_res]
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    db_no_pgvector.bind = mock_bind

    app.dependency_overrides[get_db] = lambda: db_no_pgvector

    response = await client.get("/ready")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["database"] == "ok"
    assert data["vector_store"] == "disabled"


@pytest.mark.asyncio
async def test_api_v1_system_info(client: AsyncClient) -> None:
    """Verify that /api/v1/info returns system metadata."""
    response = await client.get("/api/v1/info")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "app_name" in data
    assert "version" in data
    assert "environment" in data
    assert "debug" in data


@pytest.mark.asyncio
async def test_request_id_custom_propagation(client: AsyncClient) -> None:
    """Verify custom X-Request-ID in header is preserved and echoed back."""
    custom_id = "test-custom-req-id-12345"
    response = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("X-Request-ID") == custom_id


@pytest.mark.asyncio
async def test_request_id_auto_generation(client: AsyncClient) -> None:
    """Verify X-Request-ID is automatically generated when not provided."""
    response = await client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    req_id = response.headers.get("X-Request-ID")
    assert req_id is not None
    assert len(req_id) > 0


@pytest.mark.asyncio
async def test_not_found_error_format(client: AsyncClient) -> None:
    """Verify 404 responses conform to standardized error envelope."""
    response = await client.get("/non-existent-path")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "message" in data["error"]
    assert "request_id" in data["error"]
