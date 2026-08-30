from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    """Base user fields."""

    email: EmailStr
    full_name: str


class UserResponse(UserBase):
    """Public user response schema - NEVER includes password hashes or secrets."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserSummary(BaseModel):
    """Concise user summary representation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str
