from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class ProviderCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Database foundation for Bring-Your-Own-Key (BYOK) secret storage.

    IMPORTANT: Actual key encryption/decryption, SDK integrations, and endpoint inputs
    are intentionally deferred to subsequent phases. This model establishes the
    organization-scoped database schema for ciphertext storage.
    """

    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "credential_name",
            name="uq_provider_credentials_org_provider_name",
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False,
    )
    credential_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    encrypted_api_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="provider_credentials",
    )
