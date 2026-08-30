import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.user import User


@pytest.mark.asyncio
async def test_no_sensitive_secrets_leaked_in_api_responses(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """Verify that password_hash, token_hash, and JWT secrets never leak in responses."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Profile response
    res = await client.get("/api/v1/auth/me", headers=headers)
    body_str = res.text
    assert "password_hash" not in body_str
    assert "$argon2id$" not in body_str
    assert "token_hash" not in body_str
    assert "secret" not in body_str.lower()

    # 2. Login response
    res_login = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": test_user_and_org["password"]},
    )
    assert res_login.status_code == status.HTTP_200_OK
    login_body = res_login.text
    assert "password_hash" not in login_body
    assert "token_hash" not in login_body

    # 3. Registration response
    res_reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "leaktst@example.com",
            "password": "Password123!",
            "full_name": "Leak Test",
        },
    )
    assert res_reg.status_code == status.HTTP_201_CREATED
    reg_body = res_reg.text
    assert "password_hash" not in reg_body
    assert "token_hash" not in reg_body


@pytest.mark.asyncio
async def test_inactive_user_blocked_from_authenticated_routes(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict
) -> None:
    """Verify that an inactive user cannot access protected endpoints even with a signed token."""
    user: User = test_user_and_org["user"]
    user.is_active = False
    await db_session.commit()

    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "inactive" in response.json()["error"]["message"]
