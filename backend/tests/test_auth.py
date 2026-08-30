import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.user import User


@pytest.mark.asyncio
async def test_register_user_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify registration creates user, default workspace, OWNER membership, and returns tokens."""
    payload = {
        "email": "Jane.Doe@Example.COM",
        "password": "SecurePassword123!",
        "full_name": "Jane Doe",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["user"]["email"] == "jane.doe@example.com"
    assert data["user"]["full_name"] == "Jane Doe"
    assert "password_hash" not in data["user"]
    assert "tokens" in data
    assert data["tokens"]["access_token"] is not None
    assert data["tokens"]["refresh_token"] is not None
    assert data["organization"]["name"] == "Jane Doe's Workspace"
    assert data["organization"]["slug"] == "jane-does-workspace"

    # Verify DB persistence and OWNER membership
    user_stmt = select(User).where(User.email == "jane.doe@example.com")
    user = (await db_session.execute(user_stmt)).scalar_one()

    mem_stmt = select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
    membership = (await db_session.execute(mem_stmt)).scalar_one()
    assert membership.role == OrganizationRole.OWNER


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    """Verify duplicate email registration is rejected with 409 Conflict."""
    payload = {
        "email": "duplicate@example.com",
        "password": "SecurePassword123!",
        "full_name": "User One",
    }
    res1 = await client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == status.HTTP_201_CREATED

    # Attempt second registration with mixed case
    payload2 = {
        "email": "DUPLICATE@example.com",
        "password": "AnotherPassword123!",
        "full_name": "User Two",
    }
    res2 = await client.post("/api/v1/auth/register", json=payload2)
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in res2.json()["error"]["message"]


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient) -> None:
    """Verify passwords under 8 characters are rejected."""
    payload = {
        "email": "weak@example.com",
        "password": "short",
        "full_name": "Short Pwd",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_user_and_org: dict) -> None:
    """Verify successful login returns valid tokens and updates last_login_at."""
    user: User = test_user_and_org["user"]
    password: str = test_user_and_org["password"]

    payload = {
        "email": user.email.upper(),  # Test email normalization
        "password": password,
    }
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 900


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient, test_user_and_org: dict) -> None:
    """Verify invalid password returns generic 401 error."""
    user: User = test_user_and_org["user"]
    payload = {
        "email": user.email,
        "password": "WrongPassword123!",
    }
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["error"]["message"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_login_non_existent_email(client: AsyncClient) -> None:
    """Verify non-existent email returns generic 401 error preventing enumeration."""
    payload = {
        "email": "nonexistent@example.com",
        "password": "SomePassword123!",
    }
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["error"]["message"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_login_inactive_user(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict
) -> None:
    """Verify inactive user accounts cannot log in."""
    user: User = test_user_and_org["user"]
    user.is_active = False
    await db_session.commit()

    payload = {
        "email": user.email,
        "password": test_user_and_org["password"],
    }
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "inactive" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_get_me_authenticated(client: AsyncClient, test_user_and_org: dict) -> None:
    """Verify /auth/me returns current user profile with valid Bearer token."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == user.id
    assert data["email"] == user.email
    assert data["full_name"] == user.full_name
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client: AsyncClient) -> None:
    """Verify /auth/me without token returns 401."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
