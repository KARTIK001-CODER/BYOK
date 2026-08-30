from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decode_access_token, hash_refresh_token
from app.models.refresh_token import RefreshToken
from app.models.user import User


@pytest.mark.asyncio
async def test_refresh_token_rotation_success(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict
) -> None:
    """Verify refresh token rotation issues new tokens and revokes the old token."""
    raw_refresh = test_user_and_org["raw_refresh_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw_refresh})
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    new_access_token = data["access_token"]
    new_refresh_token = data["refresh_token"]

    assert new_access_token is not None
    assert new_refresh_token != raw_refresh

    # Verify old token is revoked in DB
    old_hash = hash_refresh_token(raw_refresh)
    old_stmt = select(RefreshToken).where(RefreshToken.token_hash == old_hash)
    old_token = (await db_session.execute(old_stmt)).scalar_one()
    assert old_token.revoked_at is not None
    assert old_token.replaced_by_token_id is not None

    # Verify new token is active
    new_hash = hash_refresh_token(new_refresh_token)
    new_stmt = select(RefreshToken).where(RefreshToken.token_hash == new_hash)
    new_token = (await db_session.execute(new_stmt)).scalar_one()
    assert new_token.revoked_at is None
    assert new_token.id == old_token.replaced_by_token_id


@pytest.mark.asyncio
async def test_refresh_token_reuse_detection(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict
) -> None:
    """
    Verify security reuse detection:
    When a revoked token is used again, the server detects reuse,
    rejects the request, and revokes all active tokens for the user.
    """
    raw_refresh = test_user_and_org["raw_refresh_token"]

    # 1. Normal rotation (revokes raw_refresh and creates new_refresh_1)
    res1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw_refresh})
    assert res1.status_code == status.HTTP_200_OK
    new_refresh_1 = res1.json()["refresh_token"]

    # 2. Present the already revoked old token again (Simulating token theft / replay attack)
    res2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw_refresh})
    assert res2.status_code == status.HTTP_401_UNAUTHORIZED
    assert "reuse detected" in res2.json()["error"]["message"]

    # 3. Verify that the legitimately issued new_refresh_1 has now ALSO been revoked
    new_hash = hash_refresh_token(new_refresh_1)
    token_stmt = select(RefreshToken).where(RefreshToken.token_hash == new_hash)
    token_record = (await db_session.execute(token_stmt)).scalar_one()
    assert token_record.revoked_at is not None


@pytest.mark.asyncio
async def test_expired_refresh_token_rejected(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict
) -> None:
    """Verify expired refresh tokens are rejected."""
    raw_refresh = test_user_and_org["raw_refresh_token"]
    old_hash = hash_refresh_token(raw_refresh)

    # Set expiration in the past
    token_stmt = select(RefreshToken).where(RefreshToken.token_hash == old_hash)
    token = (await db_session.execute(token_stmt)).scalar_one()
    token.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw_refresh})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "expired" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client: AsyncClient, test_user_and_org: dict) -> None:
    """Verify logout revokes refresh token so it cannot be refreshed anymore."""
    raw_refresh = test_user_and_org["raw_refresh_token"]

    # 1. Logout
    res_logout = await client.post("/api/v1/auth/logout", json={"refresh_token": raw_refresh})
    assert res_logout.status_code == status.HTTP_200_OK

    # 2. Attempt refresh with revoked token -> Fails
    res_refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw_refresh})
    assert res_refresh.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_access_token_validation(test_user_and_org: dict) -> None:
    """Verify JWT access token contains minimal claims and decodes cleanly."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)

    payload = decode_access_token(token)
    assert payload["sub"] == user.id
    assert payload["type"] == "access"
    assert "jti" in payload
    assert "exp" in payload
    assert "iat" in payload
    # Assert sensitive data is NOT inside token claims
    assert "password_hash" not in payload
    assert "email" not in payload
