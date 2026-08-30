from pydantic import BaseModel, EmailStr, Field

from app.schemas.organizations import OrganizationResponse
from app.schemas.users import UserResponse


class RegisterRequest(BaseModel):
    """User registration payload."""

    email: EmailStr
    password: str = Field(min_length=8, description="Minimum 8 characters")
    full_name: str = Field(min_length=1, max_length=255)
    organization_name: str | None = Field(
        default=None,
        description="Optional custom organization name. Defaults to '{full_name}'s Workspace'.",
    )


class LoginRequest(BaseModel):
    """User login payload."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Access and refresh token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token expiration time in seconds")


class RefreshRequest(BaseModel):
    """Refresh token request payload."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Logout request payload."""

    refresh_token: str


class AuthResponse(BaseModel):
    """Full authentication response upon registration."""

    user: UserResponse
    organization: OrganizationResponse
    tokens: TokenResponse
