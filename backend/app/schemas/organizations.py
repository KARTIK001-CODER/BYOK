from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.membership import OrganizationRole


class OrganizationBase(BaseModel):
    """Base organization fields."""

    name: str


class OrganizationCreate(OrganizationBase):
    """Schema for creating a new organization."""

    slug: str | None = None


class OrganizationResponse(OrganizationBase):
    """Organization response representation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    created_at: datetime


class MembershipResponse(BaseModel):
    """Organization membership representation including role."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    user_id: str
    role: OrganizationRole
    created_at: datetime
    organization: OrganizationResponse | None = None
