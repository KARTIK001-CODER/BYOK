from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.membership import OrganizationMembership
    from app.models.provider_credential import ProviderCredential


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Organization (Tenant) model representing primary isolation boundary."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    # Relationships
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        "OrganizationMembership",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    provider_credentials: Mapped[list["ProviderCredential"]] = relationship(
        "ProviderCredential",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
